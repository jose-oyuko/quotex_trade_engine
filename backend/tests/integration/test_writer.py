from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tasks import TaskSupervisor
from app.db.repositories import (
    BalanceSnapshotRepository,
    ChainRepository,
    GroupRepository,
    RiskEventRepository,
    SignalRepository,
    TradeRepository,
)
from app.db.writer import DBWriter
from app.domain.enums import AccountType, ChainStatus, TradeStatus
from app.domain.records import GroupRecord
from app.events.bus import EventBus
from app.events.types import (
    BalanceUpdated,
    ChainAdvanced,
    ChainEnded,
    ChainStarted,
    ConnectionChanged,
    RiskTripped,
    SignalReceived,
    TradeOpened,
    TradeSettled,
)
from tests.factories import (
    NOW,
    make_balance,
    make_chain,
    make_group,
    make_risk_event,
    make_signal,
    make_trade,
)

Factory = async_sessionmaker[AsyncSession]


async def add_group(session_factory: Factory) -> GroupRecord:
    async with session_factory.begin() as session:
        return await GroupRepository(session).add(make_group())


def make_writer(
    session_factory: Factory, **kwargs: int
) -> tuple[EventBus, DBWriter, TaskSupervisor]:
    bus, tasks = EventBus(), TaskSupervisor()
    return bus, DBWriter(bus, session_factory, tasks, **kwargs), tasks


async def test_published_events_become_rows(session_factory: Factory) -> None:
    group = await add_group(session_factory)
    assert group.id is not None
    bus, writer, tasks = make_writer(session_factory)
    writer.start()

    signal = make_signal(group.id)
    chain = make_chain(group.id, signal.id)
    opened = make_trade(chain.id, group.id)
    settled = replace(
        opened,
        status=TradeStatus.LOST,
        profit=Decimal("-1.00"),
        settled_at=NOW + timedelta(seconds=61),
    )
    ended = replace(chain, status=ChainStatus.EXHAUSTED, ended_at=NOW + timedelta(seconds=61))
    risk = make_risk_event(group_id=group.id)
    balance = make_balance()

    bus.publish(SignalReceived(occurred_at=NOW, signal=signal))
    bus.publish(ChainStarted(occurred_at=NOW, chain=chain))
    bus.publish(TradeOpened(occurred_at=NOW, trade=opened))
    bus.publish(TradeSettled(occurred_at=NOW, trade=settled))
    bus.publish(ChainEnded(occurred_at=NOW, chain=ended))
    bus.publish(RiskTripped(occurred_at=NOW, risk_event=risk))
    bus.publish(BalanceUpdated(occurred_at=NOW, snapshot=balance))
    await writer.stop()
    await tasks.shutdown()

    async with session_factory() as session:
        assert await SignalRepository(session).get(signal.id) == signal
        assert await ChainRepository(session).get(chain.id) == ended
        assert await TradeRepository(session).get(opened.id) == settled
        assert await RiskEventRepository(session).list_recent() == [risk]
        assert await BalanceSnapshotRepository(session).latest(AccountType.DEMO) == balance
    assert writer.stats.written == 7
    assert writer.stats.failed == 0


async def test_chain_advanced_updates_the_existing_row(session_factory: Factory) -> None:
    group = await add_group(session_factory)
    assert group.id is not None
    bus, writer, tasks = make_writer(session_factory)
    writer.start()
    chain = make_chain(group.id)
    advanced = replace(chain, step=1, consecutive_losses=1)
    bus.publish(ChainStarted(occurred_at=NOW, chain=chain))
    bus.publish(ChainAdvanced(occurred_at=NOW, chain=advanced))
    await writer.stop()
    await tasks.shutdown()
    async with session_factory() as session:
        assert await ChainRepository(session).get(chain.id) == advanced


async def test_events_that_are_not_persisted_are_ignored(session_factory: Factory) -> None:
    bus, writer, tasks = make_writer(session_factory)
    writer.start()
    bus.publish(ConnectionChanged(occurred_at=NOW, component="quotex", connected=False))
    await writer.stop()
    await tasks.shutdown()
    assert writer.stats.written == 0
    assert writer.queue_depth == 0


async def test_a_burst_is_written_in_batches(session_factory: Factory) -> None:
    group = await add_group(session_factory)
    assert group.id is not None
    bus, writer, tasks = make_writer(session_factory, batch_size=100)
    writer.start()
    count = 450
    for n in range(count):
        bus.publish(
            SignalReceived(
                occurred_at=NOW,
                signal=make_signal(group.id, telegram_message_id=n, raw_text=f"message {n}"),
            )
        )
    await writer.stop()
    await tasks.shutdown()

    async with session_factory() as session:
        stored = await SignalRepository(session).list(limit=1000)
    assert len(stored) == count
    assert writer.stats.written == count
    assert writer.stats.batches <= 6  # 450 events, at most 100 per batch: not one commit each


async def test_shutdown_flushes_everything_still_queued(session_factory: Factory) -> None:
    group = await add_group(session_factory)
    assert group.id is not None
    bus, writer, tasks = make_writer(session_factory)
    writer.start()
    for n in range(50):
        bus.publish(
            SignalReceived(occurred_at=NOW, signal=make_signal(group.id, telegram_message_id=n))
        )
    # Stop immediately: the writer task has not even had a chance to run yet.
    assert writer.queue_depth == 50
    await writer.stop()
    await tasks.shutdown()

    async with session_factory() as session:
        assert len(await SignalRepository(session).list(limit=1000)) == 50
    assert writer.queue_depth == 0


async def test_events_published_after_stop_are_not_queued(session_factory: Factory) -> None:
    group = await add_group(session_factory)
    assert group.id is not None
    bus, writer, tasks = make_writer(session_factory)
    writer.start()
    await writer.stop()
    bus.publish(SignalReceived(occurred_at=NOW, signal=make_signal(group.id)))
    await tasks.shutdown()
    assert writer.stats.written == 0


async def test_one_bad_record_does_not_take_its_batch_down(session_factory: Factory) -> None:
    group = await add_group(session_factory)
    assert group.id is not None
    bus, writer, tasks = make_writer(session_factory)
    writer.start()
    good_before = make_signal(group.id, telegram_message_id=1)
    orphan_chain = make_chain(group_id=group.id + 999)  # group does not exist: foreign key fails
    good_after = make_signal(group.id, telegram_message_id=2)
    bus.publish(SignalReceived(occurred_at=NOW, signal=good_before))
    bus.publish(ChainStarted(occurred_at=NOW, chain=orphan_chain))
    bus.publish(SignalReceived(occurred_at=NOW, signal=good_after))
    await writer.stop()
    await tasks.shutdown()

    async with session_factory() as session:
        stored = {s.id for s in await SignalRepository(session).list()}
        assert await ChainRepository(session).get(orphan_chain.id) is None
    assert stored == {good_before.id, good_after.id}
    assert (writer.stats.written, writer.stats.failed) == (2, 1)


async def test_a_full_queue_drops_new_events_and_counts_them(session_factory: Factory) -> None:
    group = await add_group(session_factory)
    assert group.id is not None
    bus, writer, tasks = make_writer(session_factory, queue_size=5)
    writer.start()
    for n in range(20):  # no await between publishes: the writer cannot drain yet
        bus.publish(
            SignalReceived(occurred_at=NOW, signal=make_signal(group.id, telegram_message_id=n))
        )
    assert writer.dropped == 15
    await writer.stop()
    await tasks.shutdown()

    async with session_factory() as session:
        stored = await SignalRepository(session).list()
    assert sorted(s.telegram_message_id for s in stored if s.telegram_message_id is not None) == [
        0,
        1,
        2,
        3,
        4,
    ]  # the oldest five survive, in order


async def test_start_twice_is_an_error(session_factory: Factory) -> None:
    _, writer, tasks = make_writer(session_factory)
    writer.start()
    try:
        writer.start()
    except RuntimeError as error:
        assert "already started" in str(error)
    else:
        raise AssertionError("expected RuntimeError")
    finally:
        await writer.stop()
        await tasks.shutdown()
