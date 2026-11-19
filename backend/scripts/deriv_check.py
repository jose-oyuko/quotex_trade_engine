"""Live check of the Deriv adapter against the real service, on the DEMO account only.

    npm run deriv:check                          connect, show the account, assets, lengths, payouts
    npm run deriv:check -- --order               also place ONE 1.00 demo trade and wait for it
    npm run deriv:check -- --asset R_100 --duration 300 --direction put --order
    npm run deriv:check -- --asset 1HZ75V --order --timeline     (Phase 24: 3 x 1.00 demo trades)

--timeline places --count (default 3) DEMO trades one after the other and prints, for each, when
every contract update and price tick arrived around its end time, when the early result (decision
D-82) was known, when Deriv marked the contract sold, and whether the two agree. Nothing is
stored.

It never uses the real account: there is no switch for it. It reads DERIV_APP_ID and
DERIV_TOKEN_DEMO from backend/.env and never prints them. What it prints is what Phase 19 could not
check offline: which assets Deriv offers you, the Rise/Fall trade lengths it allows on each (forex
and synthetic indices differ), and what it pays.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import statistics
import sys
import time
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple

from pydantic import ValidationError

from app.brokers.errors import BrokerError
from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.tasks import TaskSupervisor
from app.deriv.factory import build_deriv_adapter
from app.deriv.protocol import describe_lengths
from app.domain.enums import AccountType, Direction
from app.engine.errors import EngineStartError
from scripts._store import with_stored_logins

# (asset, trade length in seconds) whose payout is shown: forex starts at 15 minutes on Deriv,
# synthetic indices offer 1 and 5 minutes (owner, 2026-11-17).
SAMPLES = (("EURUSD", 900), ("R_75", 60), ("R_75", 300))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--asset", default="R_75", help="asset for --order (default R_75)")
    parser.add_argument("--order", action="store_true", help="place one DEMO trade and wait")
    parser.add_argument("--amount", default="1.00", help="stake for --order (default 1.00)")
    parser.add_argument("--duration", type=int, default=60, help="trade length, s (default 60)")
    parser.add_argument("--direction", choices=["call", "put"], default="call")
    parser.add_argument(
        "--timeline",
        action="store_true",
        help="with --order: time the result (D-82), --count trades",
    )
    parser.add_argument("--count", type=int, default=3, help="trades for --timeline (default 3)")
    parser.add_argument(
        "--fields", action="store_true", help="with --timeline: show the contract's fields"
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    try:
        amount = Decimal(args.amount)
    except InvalidOperation:
        print(f"--amount {args.amount!r} is not a number")
        return 2
    tasks = TaskSupervisor()
    try:
        settings = await with_stored_logins(Settings())  # the dashboard's, else `.env`
        if getattr(args, "timeline", False):  # the early result is what is being timed
            settings = settings.model_copy(update={"deriv_early_result": "ON"})
        adapter = build_deriv_adapter(
            settings, tasks=tasks, clock=SystemClock(), account_type=AccountType.DEMO
        )
    except (ValidationError, BrokerError, EngineStartError) as exc:
        print(f"Cannot start: {exc}")
        return 2

    print("Deriv, account: DEMO (this script never uses real)")
    started = time.perf_counter()
    try:
        await adapter.connect()
        print(f"[ok] connected in {time.perf_counter() - started:.2f} s")
        balance = adapter.balance()
        print(f"[ok] demo balance: {balance.balance if balance else 'unknown'} {adapter.currency}")

        assets = adapter.assets()
        markets: dict[str, list[str]] = {}
        for asset in assets:
            markets.setdefault(asset.market or "other", []).append(
                asset.asset if asset.is_open else f"{asset.asset} (closed)"
            )
        print(f"[ok] {len(assets)} assets listed:")
        for market, names in sorted(markets.items()):
            print(f"     {market}: {', '.join(names)}")

        for name in dict.fromkeys([*(asset for asset, _ in SAMPLES), args.asset]):
            print(f"\n{name}:")
            try:
                for entry in await adapter.rise_fall_offer(name):
                    print(
                        f"     Deriv says: {entry.get('contract_type')} "
                        f"{entry.get('expiry_type')} from {entry.get('min_contract_duration')!r} "
                        f"to {entry.get('max_contract_duration')!r}"
                    )
                lengths = await adapter.trade_lengths(name)
                shown = "not readable" if lengths is None else describe_lengths(lengths)
                print(f"     Rise/Fall trade lengths: {shown}")
                if not lengths:
                    show_raw(await adapter.contracts_reply(name))
            except BrokerError as exc:
                print(f"     [!!] {exc}")

        print()
        for name, duration_s in SAMPLES:
            try:
                await adapter.prepare_asset(name, duration_s)
                payout = adapter.payout(name, duration_s // 60)
                print(f"[ok] payout {name} {duration_s // 60} min: {payout}%")
            except BrokerError as exc:
                print(f"[!!] payout {name} {duration_s // 60} min: {exc}")

        if not args.order:
            print("\nDone (no trade placed; add --order to test one demo trade).")
            return 0

        if getattr(args, "timeline", False):
            return await timeline(adapter, args, amount)

        print(
            f"\nPlacing DEMO trade: {args.direction} {args.asset} {args.duration}s stake {amount}"
        )
        await adapter.prepare_asset(args.asset, args.duration)  # so the timing is a normal order's
        wall_start = time.perf_counter()
        ack = await adapter.place_order(
            args.asset, Direction(args.direction), args.duration, amount
        )
        wall_ms = (time.perf_counter() - wall_start) * 1000
        sent_to_ack_ms = (ack.t_order_acked_ns - ack.t_order_sent_ns) / 1e6
        print(f"[ok] contract {ack.order_id} confirmed: place_order took {wall_ms:.0f} ms total")
        print(f"     (send -> confirmation inside it: {sent_to_ack_ms:.0f} ms)")
        wait_s = args.duration + 60
        print(f"Waiting for the result (up to {wait_s}s)...")
        result = await adapter.await_result(ack.order_id, wait_s)
        print(f"[ok] result: {result.outcome.value}, profit {result.profit}")
        print("     CHECK: a lost trade should show a NEGATIVE profit (about -stake).")
        final = adapter.balance()
        print(f"     balance now: {final.balance if final else 'unknown'}")
        return 0
    except BrokerError as exc:
        print(f"[FAILED] {type(exc).__name__}: {exc}")
        return 1
    finally:
        await adapter.disconnect()
        await tasks.shutdown()


# ---- --timeline (decision D-82) ------------------------------------------------------------------

CONTRACT_FIELDS = (
    "is_expired",
    "is_settleable",
    "exit_spot",
    "exit_spot_time",
    "status",
    "is_sold",
)
SOLD_WAIT_S = 30.0


async def timeline(adapter: Any, args: argparse.Namespace, amount: Decimal) -> int:
    """Place `--count` demo trades one after the other and time each one's result."""
    events: list[tuple[float, str, Any]] = []
    adapter.observe(lambda kind, data: events.append((time.time(), kind, data)))
    corrections: list[Any] = []
    adapter.set_correction_handler(corrections.append)
    early_s: list[float] = []
    sold_s: list[float] = []
    agreed = 0
    await adapter.prepare_asset(args.asset, args.duration)
    for number in range(1, args.count + 1):
        events.clear()
        print(
            f"\nTrade {number}/{args.count}: {args.direction} {args.asset} "
            f"{args.duration}s {amount}"
        )
        ack = await adapter.place_order(
            args.asset, Direction(args.direction), args.duration, amount
        )
        result = await adapter.await_result(ack.order_id, args.duration + 60)
        known_at = time.time()
        for _ in range(int(SOLD_WAIT_S * 10)):  # Deriv's own result, checked in the background
            if any(kind == "contract" and _sold(data) for _, kind, data in events):
                break
            await asyncio.sleep(0.1)
        report = format_timeline(events, known_at, result.profit)
        print(report.text)
        if getattr(args, "fields", False):
            print(contract_fields(events))
        if report.early_s is not None:
            early_s.append(report.early_s)
        if report.sold_s is not None:
            sold_s.append(report.sold_s)
        agreed += report.agrees
    print("\nSummary")
    print(f"  result known after the end time: {_median(early_s)} (median of {len(early_s)})")
    print(f"  Deriv marked it sold after:      {_median(sold_s)} (median of {len(sold_s)})")
    print(
        f"  early result = Deriv's own: {agreed} of {args.count}; corrections: {len(corrections)}"
    )
    print("  The times use this PC's clock against Deriv's end time: a clock off by a second")
    print("  shifts them all by that second (Windows: Settings > Time > Sync now).")
    return 0 if not corrections else 1


class TimelineReport(NamedTuple):
    text: str
    early_s: float | None  # the result known, seconds after the end time
    sold_s: float | None  # Deriv's "sold" update received, seconds after the end time
    agrees: bool


def format_timeline(
    events: list[tuple[float, str, Any]], known_at: float, profit: Decimal
) -> TimelineReport:
    """One trade's updates and ticks, timed from its end time (pure, so it can be tested)."""
    expiry: int | None = None
    for _, kind, data in events:
        if kind == "contract" and isinstance(data.get("date_expiry"), int):
            expiry = data["date_expiry"]
    if expiry is None:
        return TimelineReport(
            f"  Deriv sent no end time for this contract; result {profit}", None, None, False
        )
    lines = [f"  end time {expiry} (epoch); times below are seconds after it, by this PC's clock"]
    sold_s: float | None = None
    official: Decimal | None = None
    for received, kind, data in events:
        after = received - expiry
        if kind == "tick":
            epoch, quote = data
            if abs(epoch - expiry) <= 3:
                lines.append(f"  {after:+7.2f}s  tick of {epoch - expiry:+d}s: {quote}")
        else:
            shown = ", ".join(f"{key}={data.get(key)!r}" for key in CONTRACT_FIELDS if key in data)
            if after >= -3:
                lines.append(f"  {after:+7.2f}s  update: {shown}")
            if _sold(data) and sold_s is None:
                sold_s = after
                with contextlib.suppress(InvalidOperation, TypeError):
                    official = Decimal(str(data.get("profit"))).quantize(Decimal("0.01"))
    early = known_at - expiry
    agrees = official is not None and official == profit
    lines.append(f"  {early:+7.2f}s  result used by the engine: profit {profit}")
    verdict = "agrees" if agrees else "DIFFERS" if official is not None else "not seen"
    lines.append(f"  Deriv's own result: {official} ({verdict})")
    return TimelineReport("\n".join(lines), early, sold_s, agrees)


FIELD_HINTS = ("entry", "exit", "expiry", "start", "payout", "price", "type", "tick", "spot")
FIELD_SKIP = ("account", "login", "transaction", "balance", "currency")


def contract_fields(events: list[tuple[float, str, Any]]) -> str:
    """What Deriv's contract updates carry (the names and values that decide a result; nothing
    about the account), from the first update and the first one after the end time."""
    contracts = [data for _, kind, data in events if kind == "contract"]
    shown = [contracts[0]] if contracts else []
    shown += [c for c in contracts if c.get("is_expired") == 1][:1]
    lines = []
    for contract in shown:
        names = sorted(contract)
        lines.append(f"  fields of an update ({len(names)}): {', '.join(names)}")
        for name in names:
            if any(h in name for h in FIELD_HINTS) and not any(s in name for s in FIELD_SKIP):
                lines.append(f"     {name} = {contract[name]!r}")
    return "\n".join(lines)


def _sold(contract: Any) -> bool:
    return isinstance(contract, Mapping) and (
        contract.get("is_sold") == 1 or contract.get("status") in ("won", "lost", "sold")
    )


def _median(values: list[float]) -> str:
    return f"{statistics.median(values):+.2f} s" if values else "-"


RAW_FIELDS = (
    "contract_category",
    "contract_type",
    "barriers",
    "expiry_type",
    "min_contract_duration",
    "max_contract_duration",
)


def show_raw(reply: Mapping[str, Any]) -> None:
    """What Deriv sent for an asset whose lengths could not be read: the shape of the answer, one
    line per distinct contract, and the first entry in full (no account data is in it)."""
    print(f"     Deriv's answer has: {sorted(reply)}")
    offer = reply.get("contracts_for")
    if not isinstance(offer, Mapping):
        print(f"     contracts_for is {type(offer).__name__}: {str(offer)[:300]}")
        return
    print(f"     contracts_for has: {sorted(offer)}")
    available = offer.get("available")
    if not isinstance(available, list) or not available:
        print(f"     available is: {str(available)[:300]}")
        return
    seen: set[str] = set()
    for entry in available:
        if not isinstance(entry, Mapping):
            continue
        line = ", ".join(f"{key}={entry.get(key)!r}" for key in RAW_FIELDS)
        if line not in seen:
            seen.add(line)
            print(f"     raw: {line}")
    print(f"     first entry in full: {json.dumps(available[0], default=str)[:1500]}")


def main() -> int:
    args = parse_args()
    configure_logging("WARNING", json_output=False)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
