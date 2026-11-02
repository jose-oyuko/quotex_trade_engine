"""Try a message on the signal parser without Telegram, Quotex or the database.

    npm run signal:try -- "EURUSD PUT 1m"
    npm run signal:try -- --file message.txt --suffix auto --tz UTC-3
    npm run signal:try -- --file message.txt --now 2026-11-01T07:20:00+00:00

It shows what the pipeline would do with the message for a group set up the way the options say:
the trade it would hand to the engine (or the reason it would not), and when. Nothing is sent or
stored. Use --file for messages with emojis: some terminals garble them on the command line.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.core.clock import SystemClock
from app.core.tasks import TaskSupervisor
from app.domain.enums import AssetSuffixMode
from app.events.bus import EventBus
from app.events.types import SignalReceived
from app.signals.models import RawMessage, Signal
from app.signals.parsers.registry import ParserRegistry
from app.signals.pipeline import GroupRoute, SignalPipeline
from app.signals.timezones import InvalidTimezoneError, parse_timezone


class FixedClock:
    """The real clock, or a chosen moment (to see how an entry time is judged)."""

    def __init__(self, now: datetime | None) -> None:
        self._now = now
        self._real = SystemClock()

    def now(self) -> datetime:
        return self._now or self._real.now()

    def monotonic_ns(self) -> int:
        return self._real.monotonic_ns()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("text", nargs="?", help="the message text (or use --file)")
    parser.add_argument("--file", type=Path, help="read the message from this UTF-8 file")
    parser.add_argument("--parser", default="legacy_v1")
    parser.add_argument("--suffix", choices=[m.value for m in AssetSuffixMode], default="auto")
    parser.add_argument("--tz", default="UTC", help="the group's zone: UTC-3, Africa/Nairobi, ...")
    parser.add_argument("--now", help="pretend it is this moment, ISO format with a zone")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    if args.file is not None:
        try:
            text = args.file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"Cannot read {args.file}: {exc}")
            return 2
    elif args.text is not None:
        text = args.text
    else:
        print("Give the message as text or with --file.")
        return 2
    try:
        tz = parse_timezone(args.tz)
        now = datetime.fromisoformat(args.now) if args.now else None
        if now is not None and now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
    except (InvalidTimezoneError, ValueError) as exc:
        print(f"Bad option: {exc}")
        return 2

    clock = FixedClock(now)
    bus = EventBus()
    inbox = bus.subscribe(SignalReceived, name="try")
    handed: list[Signal] = []
    tasks = TaskSupervisor()
    pipeline = SignalPipeline(
        bus=bus,
        clock=clock,
        parsers=ParserRegistry(),
        tasks=tasks,
        on_signal=handed.append,
    )
    pipeline.set_route(
        GroupRoute(
            group_id=1,
            chat_id=1,
            title="try",
            parser=args.parser,
            asset_suffix_mode=AssetSuffixMode(args.suffix),
            timezone=tz,
        )
    )
    pipeline.handle(
        RawMessage(
            chat_id=1,
            message_id=1,
            text=text,
            received_at=clock.now(),
            received_ns=clock.monotonic_ns(),
        )
    )

    await tasks.shutdown()  # a scheduled signal parks a timer; we only wanted to see the decision
    event = inbox.get_nowait()
    if not isinstance(event, SignalReceived):
        print("The pipeline recorded nothing (this should not happen).")
        return 1
    row = event.signal
    print(f"Status : {row.status.value}")
    if row.reason:
        print(f"Reason : {row.reason}")
    if row.asset:
        print(
            f"Trade  : {row.direction.value.upper() if row.direction else '?'} {row.asset} "
            f"for {row.duration_s} s"
        )
    if handed:
        print("Hand-over: now (the engine would place the order at once)")
    elif row.entry_time:
        print(f"Hand-over: at {row.entry_time:%Y-%m-%d %H:%M:%S} UTC (scheduled)")
    return 0


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
