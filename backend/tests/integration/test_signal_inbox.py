"""Telegram (fake) -> listener -> pipeline -> event bus -> DB writer -> database.

Proves the acceptance criterion "every received message is recorded in the signal inbox" end to
end, with the real database, and that the inbox is written off the path to the engine.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tasks import TaskSupervisor
from app.db.repositories import GroupRepository, SignalRepository
from app.db.writer import DBWriter
from app.domain.enums import AssetSuffixMode, SignalStatus
from app.events.bus import EventBus
from app.signals.models import Signal
from app.signals.parsers import ParserRegistry
from app.signals.pipeline import GroupRoute, SignalPipeline
from app.telegram import FakeTelegramSource, TelegramListener
from tests.factories import make_group, make_settings
from tests.signal_support import ManualClock

Factory = async_sessionmaker[AsyncSession]

MESSAGES = [
    "Good morning team",
    "💰5 minutes expiry USD/BDT;15:00;PUT 🟥",
    "EURUSD PUT 1m",
    "EURUSD PUT 1m",  # a repost: duplicate
    "ASSET: USD/JPY (OTC) | EXPIRATION: M1 | DIRECTION: BUY | ENTRY: 07:29",
    "1ST GALE — TIME TO 07:30",
]


async def test_every_message_ends_up_in_the_signal_inbox(session_factory: Factory) -> None:
    async with session_factory.begin() as session:
        group = await GroupRepository(session).add(replace(make_group(), id=None))
    assert group.id is not None
    clock, bus, tasks = ManualClock(), EventBus(), TaskSupervisor()  # 10:00 UTC, fixed
    writer = DBWriter(bus, session_factory, tasks)
    writer.start()

    handed_over: list[Signal] = []
    pipeline = SignalPipeline(
        bus=bus, clock=clock, parsers=ParserRegistry(), tasks=tasks, on_signal=handed_over.append
    )
    settings = make_settings(group.id, timezone="UTC", asset_suffix_mode=AssetSuffixMode.AUTO)
    pipeline.set_route(
        GroupRoute(
            group_id=group.id,
            chat_id=group.telegram_chat_id,
            title=group.title,
            parser=settings.parser,
            asset_suffix_mode=settings.asset_suffix_mode,
            timezone=UTC,
        )
    )
    source = FakeTelegramSource(clock)
    listener = TelegramListener(source, handler=pipeline.handle, bus=bus, clock=clock, tasks=tasks)
    listener.subscribe(group.telegram_chat_id)
    listener.start()
    assert await listener.wait_until_connected(2)

    for message_id, text in enumerate(MESSAGES, start=1):
        # At 10:00 UTC the entry times 15:00 and 07:29 are "too far ahead" and "already passed":
        # both are refused, and both must still be recorded.
        source.emit(
            group.telegram_chat_id,
            text,
            message_id=message_id,
            sent_at=clock.now() - timedelta(seconds=1),
        )
    await listener.stop()
    await writer.stop()
    await tasks.shutdown()

    async with session_factory() as session:
        rows = await SignalRepository(session).list(group_id=group.id, limit=100)
    assert len(rows) == len(MESSAGES)
    by_message = {row.telegram_message_id: row for row in rows}
    assert {row.raw_text for row in rows} == set(MESSAGES)  # nothing lost, nothing altered
    assert by_message[1].status is SignalStatus.NOT_PARSED
    assert by_message[2].status is SignalStatus.IGNORED and "too far" in (
        by_message[2].reason or ""
    )
    assert by_message[3].status is SignalStatus.PARSED and by_message[3].asset == "EURUSD"
    assert (
        by_message[4].status is SignalStatus.IGNORED and by_message[4].reason == "duplicate signal"
    )
    assert by_message[5].status is SignalStatus.IGNORED
    assert "already passed" in (by_message[5].reason or "")
    assert by_message[6].status is SignalStatus.NOT_PARSED
    assert all(row.reason for row in rows if row.status is not SignalStatus.PARSED)
    assert writer.stats.failed == 0
    assert [s.asset for s in handed_over] == ["EURUSD"]
