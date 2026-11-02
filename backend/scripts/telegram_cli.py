"""Live Telegram tools. They only read: nothing here sends a message or places a trade.

    npm run telegram:login                       log in once (phone, code, optional password)
    npm run telegram:dialogs                     list your chats with the ids to use for a group
    npm run telegram:listen -- --chat -100123    print what the pipeline makes of each new message

Credentials come from backend/.env (TELEGRAM_API_ID, TELEGRAM_API_HASH, optional TELEGRAM_PHONE).
The login code and any password are typed in this terminal and are never stored or printed; only
the session file backend/data/telegram.session is kept, which is git-ignored and must stay private.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from pydantic import ValidationError

from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.tasks import TaskSupervisor
from app.domain.enums import AssetSuffixMode
from app.events.bus import EventBus
from app.events.types import ConnectionChanged, SignalReceived
from app.signals.models import Signal
from app.signals.parsers.registry import ParserRegistry
from app.signals.pipeline import GroupRoute, SignalPipeline
from app.signals.timezones import InvalidTimezoneError, parse_timezone
from app.telegram.factory import build_telethon_source
from app.telegram.listener import TelegramListener
from app.telegram.login import log_in
from app.telegram.source import TelegramError, TelegramSource


async def ask(prompt: str) -> str:
    return (await asyncio.to_thread(input, f"{prompt}\n> ")).strip()


async def ask_secret(prompt: str) -> str:
    return await asyncio.to_thread(getpass.getpass, f"{prompt} (typing is hidden): ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="log in and save the session")
    commands.add_parser("dialogs", help="list chats and their ids")
    listen = commands.add_parser("listen", help="listen to chats and show parsed signals")
    listen.add_argument("--chat", type=int, action="append", required=True, help="chat id")
    listen.add_argument("--parser", default="legacy_v1")
    listen.add_argument("--suffix", choices=[m.value for m in AssetSuffixMode], default="auto")
    listen.add_argument("--tz", default="UTC", help="zone for entry times: UTC-3, Africa/Nairobi")
    return parser.parse_args()


async def do_login(settings: Settings, source: TelegramSource) -> int:
    if await source.is_authorized():
        print("[ok] already logged in; nothing to do.")
        return 0
    phone = settings.telegram_phone or await ask(
        "Phone number in international format (+<country code><number>)"
    )
    await log_in(source, phone=phone, ask_code=ask, ask_password=ask_secret)
    print(
        f"[ok] logged in. Session saved in {settings.telegram_session_path}.session "
        "(keep it private)."
    )
    return 0


async def do_dialogs(source: TelegramSource) -> int:
    if not await source.is_authorized():
        print("Not logged in. Run `npm run telegram:login` first.")
        return 1
    dialogs = await source.list_dialogs()
    print(f"{'chat id':>16}  {'kind':8}  title")
    for dialog in dialogs:
        print(f"{dialog.chat_id:>16}  {dialog.kind.value:8}  {dialog.title}")
    print(f"\n{len(dialogs)} chats. Use the chat id of the group you want in `telegram:listen`.")
    return 0


async def do_listen(args: argparse.Namespace, source: TelegramSource) -> int:
    try:
        tz = parse_timezone(args.tz)
    except InvalidTimezoneError as exc:
        print(exc)
        return 2
    clock = SystemClock()
    bus = EventBus()
    tasks = TaskSupervisor()
    inbox = bus.subscribe(SignalReceived, ConnectionChanged, name="cli")

    def ready(signal: Signal) -> None:
        when = "now" if signal.entry_at is None else f"at {signal.entry_at:%H:%M:%S} UTC"
        parse_us = (signal.t_parsed_ns - signal.t_msg_received_ns) / 1000
        print(
            f"  => SIGNAL {signal.direction.value.upper()} {signal.asset} {signal.duration_s}s "
            f"{when}   (message -> parsed: {parse_us:.0f} us)"
        )

    pipeline = SignalPipeline(
        bus=bus, clock=clock, parsers=ParserRegistry(), tasks=tasks, on_signal=ready
    )
    listener = TelegramListener(source, handler=pipeline.handle, bus=bus, clock=clock, tasks=tasks)
    chat_of_group = dict(enumerate(args.chat, start=1))
    for group_id, chat_id in chat_of_group.items():
        pipeline.set_route(
            GroupRoute(
                group_id=group_id,
                chat_id=chat_id,
                title=str(chat_id),
                parser=args.parser,
                asset_suffix_mode=AssetSuffixMode(args.suffix),
                timezone=tz,
            )
        )
    listener.set_subscriptions(args.chat)
    listener.start()
    if not await listener.wait_until_connected(30):
        print(
            f"Could not start listening (state: {listener.state.value}). Is the session logged in?"
        )
        await listener.stop()
        await tasks.shutdown()
        return 1
    print(f"Listening to {len(args.chat)} chat(s). Press Ctrl+C to stop. Nothing is traded.\n")
    try:
        while True:
            event = await inbox.get()
            if isinstance(event, ConnectionChanged):
                print(f"[telegram] connected={event.connected} {event.detail or ''}")
            elif isinstance(event, SignalReceived):
                row = event.signal
                text = " ".join(row.raw_text.split())[:70]
                print(f"[{row.status.value}] chat {chat_of_group[row.group_id]}: {text!r}")
                if row.reason:
                    print(f"  reason: {row.reason}")
    finally:
        await listener.stop()
        await tasks.shutdown()


async def run(args: argparse.Namespace) -> int:
    try:
        settings = Settings()
        source = build_telethon_source(settings, clock=SystemClock())
    except (ValidationError, TelegramError) as exc:
        print(f"Cannot start: {exc}")
        return 2
    try:
        await source.connect()
        match args.command:
            case "login":
                return await do_login(settings, source)
            case "dialogs":
                return await do_dialogs(source)
            case _:
                return await do_listen(args, source)
    except TelegramError as exc:
        print(f"[FAILED] {type(exc).__name__}: {exc}")
        return 1
    finally:
        await source.disconnect()


def main() -> int:
    args = parse_args()
    configure_logging("WARNING", json_output=False)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
