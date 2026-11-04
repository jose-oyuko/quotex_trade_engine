"""Live check of the Quotex adapter against the real service, on the DEMO account only.

    npm run quotex:diagnose                      connect, show balance and payout
    npm run quotex:diagnose -- --order           also place ONE demo order and wait for its result
    npm run quotex:diagnose -- --asset EURUSD_otc --duration 60 --amount 1 --direction put --order

It never uses the real account: there is no switch for it. It uses the logins stored on the
dashboard (the email, the password and, if you made one there, the Quotex login), else
QUOTEX_EMAIL and QUOTEX_PASSWORD from backend/.env, and never prints them. If Quotex asks for an
email PIN, type it in this terminal: the check goes on, but the PIN login is not stored by this
script, so make the login that the engine uses on the dashboard (Settings > Quotex login), where
the PIN is asked for too.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.tasks import TaskSupervisor
from app.domain.enums import AccountType, Direction
from app.engine.errors import EngineStartError
from app.quotex.errors import QuotexError
from app.quotex.factory import build_pyquotex_adapter
from scripts._store import with_stored_logins


async def read_pin(prompt: str) -> str:
    print(f"\nQuotex asks for a code: {prompt.strip()}")
    return (await asyncio.to_thread(input, "PIN> ")).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--asset", default="EURUSD", help="Quotex asset code (default EURUSD)")
    parser.add_argument("--order", action="store_true", help="place one DEMO order and wait for it")
    parser.add_argument("--amount", default="1.00", help="stake for --order (default 1.00)")
    parser.add_argument("--duration", type=int, default=60, help="expiry seconds (default 60)")
    parser.add_argument("--direction", choices=["call", "put"], default="call")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    try:
        amount = Decimal(args.amount)
    except InvalidOperation:
        print(f"--amount {args.amount!r} is not a number")
        return 2
    try:
        settings = await with_stored_logins(Settings())
        tasks = TaskSupervisor()
        adapter = build_pyquotex_adapter(
            settings,
            tasks=tasks,
            clock=SystemClock(),
            account_type=AccountType.DEMO,
            otp_callback=read_pin,
        )
    except (ValidationError, QuotexError, EngineStartError) as exc:
        print(f"Cannot start: {exc}")
        return 2

    print(f"Host: {settings.quotex_host}   Account: DEMO (this script never uses real)")
    started = time.perf_counter()
    try:
        await adapter.connect()
        print(f"[ok] connected and warmed up in {time.perf_counter() - started:.2f} s")

        balance = adapter.balance()
        print(
            f"[{'ok' if balance else '??'}] demo balance: "
            f"{balance.balance if balance else 'unknown'}"
        )

        is_open = adapter.is_open(args.asset)
        print(
            f"[{'ok' if is_open else '!!'}] {args.asset} is "
            f"{'open' if is_open else 'closed/unknown'}"
        )
        for minutes in (1, 5):
            print(f"[ok] payout {args.asset} {minutes}m: {adapter.payout(args.asset, minutes)}%")

        if not args.order:
            print("\nDone (no order placed; add --order to test one demo trade).")
            return 0
        if not is_open:
            print("Not placing an order: the asset is closed. Try another with --asset.")
            return 1

        print(
            f"\nPlacing DEMO order: {args.direction} {args.asset} {args.duration}s stake {amount}"
        )
        # Do the one-time price subscription first so the timing below is a normal order's.
        await adapter.prepare_asset(args.asset, args.duration)
        wall_start = time.perf_counter()
        ack = await adapter.place_order(
            args.asset, Direction(args.direction), args.duration, amount
        )
        wall_ms = (time.perf_counter() - wall_start) * 1000
        sent_to_ack_ms = (ack.t_order_acked_ns - ack.t_order_sent_ns) / 1e6
        print(f"[ok] order {ack.order_id} confirmed: place_order took {wall_ms:.0f} ms total")
        print(f"     (send -> confirmation inside it: {sent_to_ack_ms:.0f} ms)")

        wait_s = args.duration + 60
        print(f"Waiting for the result (up to {wait_s}s)...")
        result = await adapter.await_result(ack.order_id, wait_s)
        print(f"[ok] result: {result.outcome.value}, profit {result.profit}")
        print("     CHECK: a lost trade should show a NEGATIVE profit (about -stake).")
        final = adapter.balance()
        print(f"     balance now: {final.balance if final else 'unknown'}")
        return 0
    except QuotexError as exc:
        print(f"[FAILED] {type(exc).__name__}: {exc}")
        if "resolve host" in str(exc).lower():
            print(  # the old bot's "getaddrinfo failed": the domain no longer exists
                f"     The name {settings.quotex_host!r} does not resolve. Set QUOTEX_HOST in "
                "backend/.env to the broker's current domain (see README)."
            )
        return 1
    finally:
        await adapter.disconnect()
        await tasks.shutdown()


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
