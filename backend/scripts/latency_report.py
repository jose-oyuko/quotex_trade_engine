"""How fast were your real trades, from the message to the order? Reads the stored trades.

    npm run latency                      every account, all time
    npm run latency -- --account demo --days 7

Every trade records monotonic timestamps at each step of the execution path (docs/ARCHITECTURE.md
section 4). This report turns them into medians and percentiles, so you can answer "how long between
the Telegram message arriving and the order leaving?" with your own live data, not a benchmark.

  signal -> order    message received -> order sent   (the first trade of each chain)
  decision -> order  decision made    -> order sent   (every trade, follow-ups included)
  order -> ack       order sent       -> Quotex confirmed it (mostly the network)

What is NOT in these figures: the time the message spent travelling from the group to Telegram's
servers to you, and what Quotex does after confirming. Times between two steps are only compared
within one trade, so a restart of the app in between never distorts them.
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings

MEASURES = {
    "signal -> order": ("t_msg_received_ns", "t_order_sent_ns"),
    "decision -> order": ("t_decided_ns", "t_order_sent_ns"),
    "order -> ack": ("t_order_sent_ns", "t_order_acked_ns"),
}


@dataclass(slots=True, frozen=True)
class Stats:
    count: int
    median_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


def percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of an already sorted, non-empty list."""
    index = min(len(sorted_values) - 1, max(0, round(fraction * (len(sorted_values) - 1))))
    return sorted_values[index]


def describe(milliseconds: list[float]) -> Stats | None:
    if not milliseconds:
        return None
    ordered = sorted(milliseconds)
    return Stats(
        count=len(ordered),
        median_ms=statistics.median(ordered),
        p95_ms=percentile(ordered, 0.95),
        p99_ms=percentile(ordered, 0.99),
        max_ms=ordered[-1],
    )


def collect(
    db: sqlite3.Connection, *, account: str | None = None, since: datetime | None = None
) -> dict[str, dict[str, Stats | None]]:
    """For each account type (and `all`), the statistics of each measure."""
    where, params = ["status IN ('won','lost','draw','open')"], []
    if account:
        where.append("account_type = ?")
        params.append(account)
    if since is not None:
        where.append("created_at >= ?")
        params.append(since.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"))
    rows = db.execute(
        "SELECT account_type, step, t_msg_received_ns, t_decided_ns, t_order_sent_ns, "  # noqa: S608
        f"t_order_acked_ns FROM trades WHERE {' AND '.join(where)}",
        params,
    ).fetchall()
    series: dict[str, dict[str, list[float]]] = {}
    for account_type, _step, received, decided, sent, acked in rows:
        columns = {
            "t_msg_received_ns": received,
            "t_decided_ns": decided,
            "t_order_sent_ns": sent,
            "t_order_acked_ns": acked,
        }
        for label, (start, end) in MEASURES.items():
            a, b = columns[start], columns[end]
            if a is None or b is None or b < a:
                continue  # a follow-up has no message time; a negative would be a clock restart
            series.setdefault(account_type, {}).setdefault(label, []).append((b - a) / 1_000_000)
    return {
        acc: {label: describe(values) for label, values in by_label.items()}
        for acc, by_label in sorted(series.items())
    }


def format_report(result: dict[str, dict[str, Stats | None]]) -> str:
    if not result:
        return "No timed trades yet. Trades placed by the engine carry these timings."
    lines: list[str] = []
    for account, measures in result.items():
        lines.append(f"{account.upper()} account")
        lines.append(
            f"  {'step':<19}{'trades':>8}{'median':>11}{'95th':>11}{'99th':>11}{'worst':>11}"
        )
        for label in MEASURES:
            stats = measures.get(label)
            if stats is None:
                lines.append(f"  {label:<19}{'-':>8}")
                continue
            lines.append(
                f"  {label:<19}{stats.count:>8}{stats.median_ms:>9.2f}ms{stats.p95_ms:>9.2f}ms"
                f"{stats.p99_ms:>9.2f}ms{stats.max_ms:>9.2f}ms"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--account", choices=("demo", "real"))
    parser.add_argument("--days", type=int, help="only trades from the last N days")
    parser.add_argument("--database", type=Path, help="a database file (default: the app's)")
    args = parser.parse_args(argv)
    try:
        path = args.database or Settings().database_path
    except ValidationError as exc:
        sys.stderr.write(f"Invalid configuration:\n{exc}\n")
        return 2
    if not Path(path).is_file():
        sys.stderr.write(f"No database at {path}.\n")
        return 1
    since = datetime.now(UTC) - timedelta(days=args.days) if args.days else None
    db = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        print(format_report(collect(db, account=args.account, since=since)))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
