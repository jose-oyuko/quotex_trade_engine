"""Benchmarks for the event path.

Stated limit (Phase 1 acceptance criterion): publishing 10,000 events takes at most 250 ms in
total (25 microseconds each on average), measured on the publisher's side, with the DBWriter and
a second never-reading subscriber attached. The measured numbers are printed; run
`pytest -s tests/integration/test_event_throughput.py` to see them.
"""

import asyncio
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tasks import TaskSupervisor
from app.db.repositories import GroupRepository, SignalRepository
from app.db.writer import DBWriter
from app.events.bus import EventBus
from app.events.types import SignalReceived
from tests.factories import NOW, make_group, make_signal

EVENT_COUNT = 10_000
TOTAL_LIMIT_S = 0.250

Factory = async_sessionmaker[AsyncSession]


async def make_events(session_factory: Factory, count: int) -> list[SignalReceived]:
    async with session_factory.begin() as session:
        group = await GroupRepository(session).add(make_group())
    assert group.id is not None
    return [
        SignalReceived(
            occurred_at=NOW, signal=make_signal(group.id, telegram_message_id=n, raw_text=f"m{n}")
        )
        for n in range(count)
    ]


def start_writer(session_factory: Factory) -> tuple[EventBus, DBWriter, TaskSupervisor]:
    bus, tasks = EventBus(), TaskSupervisor()
    writer = DBWriter(bus, session_factory, tasks)
    writer.start()
    bus.subscribe(name="websocket_hub_stand_in")  # a second consumer that never reads
    return bus, writer, tasks


async def test_publishing_10000_events_in_a_burst_is_cheap(session_factory: Factory) -> None:
    events = await make_events(session_factory, EVENT_COUNT)
    bus, writer, tasks = start_writer(session_factory)

    started = time.perf_counter()
    for event in events:
        bus.publish(event)
    publish_s = time.perf_counter() - started

    queued = writer.queue_depth
    await tasks.shutdown()  # the background write of 10,000 rows is not what is measured here
    print(
        f"\n[benchmark] publish {EVENT_COUNT} events: {publish_s * 1000:.1f} ms total, "
        f"{publish_s / EVENT_COUNT * 1e6:.2f} us/event"
    )
    assert publish_s < TOTAL_LIMIT_S
    assert writer.dropped == 0
    assert queued == EVENT_COUNT  # nothing was lost or blocked: all queued for the writer


async def test_publish_stays_fast_while_the_writer_is_busy_with_the_database(
    session_factory: Factory,
) -> None:
    """Publish in chunks with short pauses so the writer really is committing while we publish.
    The slowest single publish call is what a trade on the hot path would experience."""
    events = await make_events(session_factory, EVENT_COUNT)
    bus, writer, tasks = start_writer(session_factory)

    slowest_ns = 0
    for start in range(0, EVENT_COUNT, 100):
        for event in events[start : start + 100]:
            before = time.perf_counter_ns()
            bus.publish(event)
            slowest_ns = max(slowest_ns, time.perf_counter_ns() - before)
        await asyncio.sleep(0.005)

    taken_by_writer = EVENT_COUNT - writer.queue_depth
    await tasks.shutdown()
    print(
        f"\n[benchmark] slowest single publish while the writer was writing: "
        f"{slowest_ns / 1000:.1f} us ({taken_by_writer} events already taken by the writer)"
    )
    assert taken_by_writer > 0  # the writer was genuinely busy at the same time
    assert slowest_ns < 5_000_000  # 5 ms: far above normal, only guards against real blocking


async def test_background_write_throughput_is_reported(session_factory: Factory) -> None:
    count = 1_000
    events = await make_events(session_factory, count)
    bus, writer, tasks = start_writer(session_factory)
    for event in events:
        bus.publish(event)

    started = time.perf_counter()
    await writer.stop()
    elapsed = time.perf_counter() - started
    await tasks.shutdown()

    print(
        f"\n[benchmark] DBWriter wrote {count} rows in {elapsed:.2f} s "
        f"({count / elapsed:.0f} rows/s, {writer.stats.batches} batches)"
    )
    async with session_factory() as session:
        assert len(await SignalRepository(session).list(limit=1000)) == count
    assert writer.stats.written == count
