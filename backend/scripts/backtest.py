"""Run a backtest on the stored prices from the terminal (decision D-84). Nothing is traded.

    npm run backtest -- --asset 1HZ75V --from 2026-11-18 --to 2026-11-18 --window 10:00-14:00 \\
        --strategy martingale:2,4,8 --strategy growing_flip:2,4,8,16,32,64,128,256

Download the prices first (`npm run history:download` or the Backtest page). The run is kept with
the others, so the dashboard's Backtest page shows it too. `--strategy NAME:MULTIPLIERS` may be
repeated (up to 6); `no_martingale` takes no multipliers.

Trend sessions (Phase 31): `--opens window,breakout` replays each strategy all through the window
and only after breakouts, side by side; `--pattern`, `--candles`, `--breakout-candles`,
`--breakout-by` and `--trend-max` (candles, 0 = until the next consolidation) set the trends;
`--check-from`/`--check-to` add a second period that judges the settings.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, time
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.backtest.replay import BacktestSetup, OpenRule, StrategySetup
from app.backtest.store import BacktestStore
from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.tasks import TaskSupervisor
from app.domain.enums import SessionMode, Strategy
from app.engine.strategies import max_steps_of
from app.events.bus import EventBus
from app.market.detector import BreakBy, MarketRules, Pattern
from app.services.backtests import BacktestService


def strategy(text: str) -> StrategySetup:
    name, _, multipliers = text.partition(":")
    try:
        kind = Strategy(name.strip())
        values = tuple(Decimal(m) for m in multipliers.split(",") if m.strip())
    except (ValueError, InvalidOperation) as exc:
        raise argparse.ArgumentTypeError(f"not a strategy: {text!r}") from exc
    limit = max_steps_of(kind)
    if limit is not None and len(values) > limit:
        raise argparse.ArgumentTypeError(f"{kind.value} has at most {limit} steps")
    if kind is Strategy.NO_MARTINGALE and values:
        raise argparse.ArgumentTypeError("no_martingale takes no multipliers")
    return StrategySetup(kind, len(values), values)


def opens(text: str) -> tuple[OpenRule, ...]:
    try:
        return tuple(OpenRule(o.strip()) for o in text.split(",") if o.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not window/breakout: {text!r}") from exc


def run_label(run: dict[str, object]) -> str:
    """A column head: the strategy, and how and where it ran when that is not the default."""
    label = str(run["strategy"])
    if run.get("opens", "window") == "breakout":
        label += " trend"
    if run.get("period", 1) == 2:
        label += " (2)"
    return label


def window(text: str) -> tuple[time, time]:
    start, _, end = text.partition("-")
    return time.fromisoformat(start), time.fromisoformat(end)


def table(summary: dict[str, object]) -> str:
    rows = [
        ("profit", "profit"),
        ("worst drawdown", "worst_drawdown"),
        ("largest stake", "largest_stake"),
        ("most in play", "most_in_play"),
        ("pairs", "pairs"),
        ("hours open", "active_s"),
        ("chains", "chains"),
        ("lost every step", "exhausted"),
        ("lost in a row", "longest_losing_run"),
        ("trades", "trades"),
        ("no price data", "no_data_rounds"),
    ]
    strategies = summary["strategies"]
    assert isinstance(strategies, list)  # noqa: S101 - our own JSON
    heads = [run_label(s) for s in strategies]
    width = max(17, *(len(h) + 2 for h in heads))
    lines = ["".ljust(17) + "".join(h.rjust(width) for h in heads)]
    for label, key in rows:
        cells = [
            f"{int(s[key]) / 3600:.1f}" if key == "active_s" else str(s[key]) for s in strategies
        ]
        lines.append(label.ljust(17) + "".join(c.rjust(width) for c in cells))
    lines.append("\nchains won at step 0, 1, 2 ...:")
    lines.extend(f"  {run_label(s)}: {s['won_at_step']}" for s in strategies)
    if any(s.get("period", 1) == 2 for s in strategies):
        lines.append("\n(2): the second period, which judges settings chosen on the first")
    return "\n".join(lines)


async def run(settings: Settings, setup: BacktestSetup) -> int:
    store = BacktestStore(settings.history_path)
    tasks = TaskSupervisor()
    service = BacktestService(store=store, bus=EventBus(), tasks=tasks, clock=SystemClock())
    await asyncio.to_thread(store.prepare, SystemClock().now(), cut_running=False)
    try:
        row = await service.start(setup)
    except DomainError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    await service.wait()
    await tasks.shutdown()
    done = await service.get(row.id)
    if done.state != "done" or done.summary is None:
        sys.stderr.write(f"{done.state}: {done.error}\n")
        return 1
    summary = json.loads(done.summary)
    print(f"{done.name}: {summary['windows']} window(s), replayed in {summary['seconds']} s")
    print(f"assumed payout {setup.payout_pct}%; network drops and missed steps not simulated\n")
    print(table(summary))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--asset", required=True)
    parser.add_argument("--from", dest="first", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="last", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--window", type=window, default=(time(0), time(23, 59)), help="HH:MM-HH:MM"
    )
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--length", type=int, default=60, help="trade length in seconds")
    parser.add_argument("--mode", choices=[m.value for m in SessionMode], default="sequential")
    parser.add_argument("--open-pairs", type=int, default=1)
    parser.add_argument("--stake", type=Decimal, default=Decimal("1.00"))
    parser.add_argument("--payout", type=Decimal, default=Decimal(88), help="percent")
    parser.add_argument("--strategy", type=strategy, action="append", required=True)
    parser.add_argument("--opens", type=opens, default=(OpenRule.WINDOW,), help="window,breakout")
    parser.add_argument("--pattern", choices=[p.value for p in Pattern], default="alternating")
    parser.add_argument("--candles", type=int, default=5, help="candles in the pattern")
    parser.add_argument("--breakout-candles", type=int, default=2)
    parser.add_argument("--breakout-by", choices=[b.value for b in BreakBy], default="close")
    parser.add_argument(
        "--trend-max", type=int, default=20, help="candles after a breakout; 0: no limit"
    )
    parser.add_argument("--check-from", type=date.fromisoformat, default=None)
    parser.add_argument("--check-to", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    if (args.check_from is None) != (args.check_to is None):
        parser.error("--check-from and --check-to go together")
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.stderr.write(f"Invalid configuration:\n{exc}\n")
        return 2
    setup = BacktestSetup(
        asset=args.asset,
        first_day=args.first,
        last_day=args.last,
        start_time=args.window[0],
        end_time=args.window[1],
        timezone=args.timezone,
        weekdays=(0, 1, 2, 3, 4, 5, 6),
        duration_s=args.length,
        mode=SessionMode(args.mode),
        pause_s=0,
        max_open_pairs=args.open_pairs,
        max_pairs=None,
        profit_target=None,
        loss_limit=None,
        base_stake=args.stake,
        payout_pct=args.payout,
        strategies=tuple(args.strategy[:6]),
        opens=args.opens,
        market=MarketRules(
            pattern=Pattern(args.pattern),
            candles=args.candles,
            breakout_candles=args.breakout_candles,
            breakout_by=BreakBy(args.breakout_by),
        ),
        trend_max_candles=args.trend_max or None,
        check_first_day=args.check_from,
        check_last_day=args.check_to,
    )
    return asyncio.run(run(settings, setup))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
