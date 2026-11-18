"""Live check of the Deriv adapter against the real service, on the DEMO account only.

    npm run deriv:check                          connect, show the account, assets, lengths, payouts
    npm run deriv:check -- --order               also place ONE 1.00 demo trade and wait for it
    npm run deriv:check -- --asset R_100 --duration 300 --direction put --order

It never uses the real account: there is no switch for it. It reads DERIV_APP_ID and
DERIV_TOKEN_DEMO from backend/.env and never prints them. What it prints is what Phase 19 could not
check offline: which assets Deriv offers you, the Rise/Fall trade lengths it allows on each (forex
and synthetic indices differ), and what it pays.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

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
