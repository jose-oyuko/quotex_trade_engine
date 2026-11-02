"""The DB writer when the database is down or locked: nothing is lost unless the outage outlasts the
patience or the queue overflows, and shutdown is never held up for long."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import replace

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tasks import TaskSupervisor
from app.db.repositories import ChainRepository, GroupRepository, SignalRepository, TradeRepository
from app.db.writer import DBWriter
from app.events.bus import EventBus
from app.events.types import ChainAdvanced, ChainStarted, SignalReceived, TradeOpened
from tests.factories import NOW, make_chain, make_group, make_signal, make_trade

Factory = async_sessionmaker[AsyncSession]


class FlakyFactory:
    """A session factory that fails like a locked or unreachable database while `down` is set."""

    def __init__(self, real: Factory) -> None:
        self._real = real
        self.down = False
        self.failures = 0
        self.error: Exception = OperationalError("INSERT", {}, Exception("database is locked"))

    def begin(self) -> AbstractAsyncContextManager[AsyncSession]:
        if self.down:
            self.failures += 1
            raise self.error
        return self._real.begin()

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._real()


class Clock:
    """Time that only moves when the writer sleeps, so an outage of minutes takes no real time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self.on_sleep = lambda: None

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        self.on_sleep()
        await asyncio.sleep(0)


def build(
    real: Factory, **kwargs: float
) -> tuple[EventBus, DBWriter, TaskSupervisor, FlakyFactory, Clock]:
    flaky, clock, bus, tasks = FlakyFactory(real), Clock(), EventBus(), TaskSupervisor()
    writer = DBWriter(
        bus,
        flaky,  # type: ignore[arg-type]
        tasks,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        rng=lambda: 0.5,
        **kwargs,  # type: ignore[arg-type]
    )
    return bus, writer, tasks, flaky, clock


async def group_id(real: Factory) -> int:
    async with real.begin() as session:
        group = await GroupRepository(session).add(make_group())
    assert group.id is not None
    return group.id


async def until(check, tries: int = 2000) -> None:  # type: ignore[no-untyped-def]
    for _ in range(tries):
        if check():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not reached")


async def test_events_published_during_an_outage_are_written_when_the_database_comes_back(
    session_factory: Factory,
) -> None:
    gid = await group_id(session_factory)
    bus, writer, tasks, flaky, clock = build(session_factory)
    writer.start()
    flaky.down = True
    signal, chain = make_signal(gid), make_chain(gid)
    bus.publish(SignalReceived(occurred_at=NOW, signal=signal))
    bus.publish(ChainStarted(occurred_at=NOW, chain=chain))
    await until(lambda: len(clock.sleeps) >= 4)  # it is waiting, not giving up
    assert writer.retrying and writer.stats.failed == 0 and writer.stats.written == 0

    bus.publish(ChainAdvanced(occurred_at=NOW, chain=replace(chain, step=1)))  # arrives mid-outage
    flaky.down = False
    await writer.stop()
    await tasks.shutdown()

    async with session_factory() as session:
        assert await SignalRepository(session).get(signal.id) == signal
        stored = await ChainRepository(session).get(chain.id)
    assert stored is not None and stored.step == 1  # in order: started, then advanced
    assert writer.stats.failed == 0 and writer.stats.written == 3
    assert writer.retrying is False


async def test_the_wait_between_attempts_grows_and_is_capped(session_factory: Factory) -> None:
    gid = await group_id(session_factory)
    bus, writer, tasks, flaky, clock = build(session_factory)
    writer.start()
    flaky.down = True
    bus.publish(SignalReceived(occurred_at=NOW, signal=make_signal(gid)))
    await until(lambda: len(clock.sleeps) >= 8)
    flaky.down = False
    await writer.stop()
    await tasks.shutdown()
    assert clock.sleeps[:5] == [0.2, 0.4, 0.8, 1.6, 3.2]  # doubling (no jitter with rng = 0.5)
    assert max(clock.sleeps) == 5.0  # and never longer than the cap


async def test_an_outage_that_outlasts_the_patience_drops_the_batch_loudly_and_carries_on(
    session_factory: Factory,
) -> None:
    gid = await group_id(session_factory)
    bus, writer, tasks, flaky, clock = build(session_factory, max_outage_s=30.0)
    writer.start()
    flaky.down = True
    lost = make_signal(gid, raw_text="lost during the outage")
    bus.publish(SignalReceived(occurred_at=NOW, signal=lost))
    await until(lambda: writer.stats.failed == 1)
    assert clock.now >= 30.0 and writer.retrying is False

    flaky.down = False  # the database returns: the writer is still alive and writes again
    kept = make_signal(gid, raw_text="after the outage")
    bus.publish(SignalReceived(occurred_at=NOW, signal=kept))
    await writer.stop()
    await tasks.shutdown()
    async with session_factory() as session:
        assert await SignalRepository(session).get(lost.id) is None
        assert await SignalRepository(session).get(kept.id) == kept
    assert (writer.stats.failed, writer.stats.written) == (1, 1)


async def test_shutdown_during_an_outage_gives_up_quickly_instead_of_hanging(
    session_factory: Factory,
) -> None:
    gid = await group_id(session_factory)
    bus, writer, tasks, flaky, clock = build(session_factory)  # ten minutes of patience
    writer.start()
    flaky.down = True
    bus.publish(SignalReceived(occurred_at=NOW, signal=make_signal(gid)))
    await until(lambda: writer.retrying)

    await asyncio.wait_for(writer.stop(), timeout=5)  # returns; it does not wait ten minutes
    await tasks.shutdown()
    assert writer.stats.failed == 1 and clock.now < 60  # a few attempts, then it let go


async def test_the_queue_is_bounded_during_an_outage_and_the_overflow_is_counted(
    session_factory: Factory,
) -> None:
    gid = await group_id(session_factory)
    bus, writer, tasks, flaky, _ = build(session_factory, queue_size=5, batch_size=2)
    writer.start()
    flaky.down = True
    first = make_signal(gid)
    bus.publish(SignalReceived(occurred_at=NOW, signal=first))
    await until(lambda: writer.retrying)  # the first batch is in the writer's hands
    for n in range(20):
        bus.publish(SignalReceived(occurred_at=NOW, signal=make_signal(gid, telegram_message_id=n)))
    assert writer.queue_depth <= 5 and writer.dropped >= 15  # bounded; the rest counted, not hidden
    flaky.down = False
    await writer.stop()
    await tasks.shutdown()
    assert writer.stats.written >= 6 and writer.stats.failed == 0  # what was kept is all written


async def test_a_record_the_database_refuses_is_still_isolated_from_the_rest(
    session_factory: Factory,
) -> None:
    gid = await group_id(session_factory)
    bus, writer, tasks, _, clock = build(session_factory)
    writer.start()
    chain = make_chain(gid)
    orphan = make_trade(chain.id, gid)  # refers to a chain that was never stored: foreign key fails
    good = make_signal(gid)
    bus.publish(TradeOpened(occurred_at=NOW, trade=orphan))
    bus.publish(SignalReceived(occurred_at=NOW, signal=good))
    await writer.stop()
    await tasks.shutdown()
    async with session_factory() as session:
        assert await SignalRepository(session).get(good.id) == good
        assert await TradeRepository(session).get(orphan.id) is None
    assert (writer.stats.written, writer.stats.failed) == (1, 1)
    assert clock.sleeps == []  # a bad record is not an outage: no waiting


async def test_an_integrity_error_is_not_mistaken_for_an_outage(session_factory: Factory) -> None:
    gid = await group_id(session_factory)
    bus, writer, tasks, flaky, clock = build(session_factory)
    flaky.error = IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
    writer.start()
    flaky.down = True
    bus.publish(SignalReceived(occurred_at=NOW, signal=make_signal(gid)))
    await until(lambda: writer.stats.failed >= 1)
    flaky.down = False
    await writer.stop()
    await tasks.shutdown()
    assert clock.sleeps == []  # failed straight away: it did not wait or retry
