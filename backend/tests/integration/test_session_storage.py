"""Trading sessions in the database: the tables, the hidden group, what the writer stores, and what
start-up reads back (decisions D-71 to D-73)."""

from __future__ import annotations

from dataclasses import replace
from datetime import time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tasks import TaskSupervisor
from app.db.recovery import load_recovery_state
from app.db.repositories import ChainRepository, GroupRepository, SessionRepository
from app.db.writer import DBWriter
from app.domain.enums import (
    AssetSuffixMode,
    GroupSource,
    RepeatKind,
    RunEndReason,
    RunState,
    SessionMode,
)
from app.domain.ids import new_id
from app.domain.records import GroupRecord, SessionRecord
from app.events.bus import EventBus
from app.events.types import ChainStarted, SessionRunChanged
from tests.factories import (
    NOW,
    make_chain,
    make_group,
    make_session,
    make_session_run,
    make_settings,
)

Factory = async_sessionmaker[AsyncSession]


async def add_session(factory: Factory, **overrides: object) -> tuple[GroupRecord, SessionRecord]:
    """A session with its hidden group (no Telegram chat) and strategy settings."""
    async with factory.begin() as db:
        groups = GroupRepository(db)
        group = await groups.add(
            make_group(telegram_chat_id=None, title="Session: Test", source=GroupSource.SESSION)
        )
        assert group.id is not None
        await groups.save_settings(
            make_settings(group.id, parser="session", asset_suffix_mode=AssetSuffixMode.NONE)
        )
        stored = await SessionRepository(db).add(make_session(group_id=group.id, **overrides))
    return group, stored


async def test_a_session_keeps_everything_it_was_saved_with(session_factory: Factory) -> None:
    _, saved = await add_session(
        session_factory,
        name="Night",
        timezone="UTC-3",
        start_time=time(23, 0),
        end_time=time(1, 30),
        weekdays=(0, 2, 4),
        profit_target=Decimal("12.50"),
        loss_limit=Decimal("30.00"),
        max_pairs=7,
        pause_s=120,
        duration_s=900,
        id=None,
    )
    assert saved.id is not None
    async with session_factory() as db:
        loaded = await SessionRepository(db).get(saved.id)
    assert loaded == saved
    assert loaded is not None
    assert loaded.weekdays == (0, 2, 4) and loaded.profit_target == Decimal("12.50")
    assert (loaded.start_time, loaded.end_time) == (time(23, 0), time(1, 30))


async def test_a_session_group_has_no_chat_and_there_can_be_several(
    session_factory: Factory,
) -> None:
    first, _ = await add_session(session_factory, id=None)
    second, _ = await add_session(session_factory, id=None, name="Other")
    assert first.telegram_chat_id is None and second.telegram_chat_id is None
    assert first.id != second.id

    async with session_factory.begin() as db:
        telegram = await GroupRepository(db).add(make_group())  # a real Telegram group
    async with session_factory() as db:
        groups = GroupRepository(db)
        assert [g.id for g in await groups.list_all(source=GroupSource.TELEGRAM)] == [telegram.id]
        assert {g.id for g in await groups.list_all(source=GroupSource.SESSION)} == {
            first.id,
            second.id,
        }
        assert len(await groups.list_all()) == 3


async def test_two_telegram_groups_still_cannot_share_a_chat(session_factory: Factory) -> None:
    async with session_factory.begin() as db:
        await GroupRepository(db).add(make_group())
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as db:
            await GroupRepository(db).add(make_group(title="same chat again"))


async def test_updating_a_session_keeps_its_group_and_its_creation_time(
    session_factory: Factory,
) -> None:
    group, saved = await add_session(session_factory, id=None)
    async with session_factory.begin() as db:
        await SessionRepository(db).update(
            replace(
                saved,
                name="Edited",
                group_id=999,
                created_at=NOW + timedelta(days=9),
                enabled=False,
                weekdays=(5, 6),
            )
        )
    async with session_factory() as db:
        loaded = await SessionRepository(db).get(saved.id or 0)
    assert loaded is not None
    assert (loaded.name, loaded.enabled, loaded.weekdays) == ("Edited", False, (5, 6))
    assert loaded.group_id == group.id and loaded.created_at == saved.created_at


async def test_a_session_with_a_run_cannot_be_deleted_from_under_it(
    session_factory: Factory,
) -> None:
    _, saved = await add_session(session_factory, id=None)
    assert saved.id is not None
    async with session_factory.begin() as db:
        await SessionRepository(db).upsert_run(make_session_run(saved.id))
    async with session_factory() as db:
        assert await SessionRepository(db).has_runs(saved.id)
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as db:
            await SessionRepository(db).delete(saved.id)


async def test_runs_are_listed_newest_first_and_counted(session_factory: Factory) -> None:
    _, saved = await add_session(session_factory, id=None)
    assert saved.id is not None
    runs = [
        make_session_run(saved.id, started_at=NOW + timedelta(hours=n), state=RunState.ENDED)
        for n in range(3)
    ]
    async with session_factory.begin() as db:
        for run in runs:
            await SessionRepository(db).upsert_run(run)
    async with session_factory() as db:
        repo = SessionRepository(db)
        listed = await repo.list_runs(session_id=saved.id)
        assert [r.id for r in listed] == [r.id for r in reversed(runs)]
        assert await repo.count_runs(session_id=saved.id) == 3
        assert await repo.count_runs(session_id=999) == 0
        assert len(await repo.list_runs(limit=2)) == 2


async def test_a_run_is_stored_again_as_it_moves_on(session_factory: Factory) -> None:
    _, saved = await add_session(session_factory, id=None)
    assert saved.id is not None
    run = make_session_run(saved.id)
    async with session_factory.begin() as db:
        await SessionRepository(db).upsert_run(run)
    ended = replace(
        run,
        state=RunState.ENDED,
        end_reason=RunEndReason.PROFIT_TARGET,
        ended_at=NOW + timedelta(minutes=50),
        pairs_opened=4,
        profit=Decimal("-3.20"),
        note="done",
    )
    async with session_factory.begin() as db:
        await SessionRepository(db).upsert_run(ended)
    async with session_factory() as db:
        assert await SessionRepository(db).get_run(run.id) == ended
        assert await SessionRepository(db).count_runs() == 1


async def test_a_chain_remembers_its_run_and_pair(session_factory: Factory) -> None:
    group, saved = await add_session(session_factory, id=None)
    assert group.id is not None and saved.id is not None
    run = make_session_run(saved.id)
    chain = make_chain(group.id, session_run_id=run.id, pair_no=3)
    async with session_factory.begin() as db:
        await SessionRepository(db).upsert_run(run)
        await ChainRepository(db).upsert(chain)
    async with session_factory() as db:
        loaded = await ChainRepository(db).get(chain.id)
    assert loaded is not None and (loaded.session_run_id, loaded.pair_no) == (run.id, 3)


async def test_a_chain_cannot_point_at_a_run_that_does_not_exist(session_factory: Factory) -> None:
    group, _ = await add_session(session_factory, id=None)
    assert group.id is not None
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as db:
            await ChainRepository(db).upsert(make_chain(group.id, session_run_id=new_id()))


async def test_the_writer_stores_run_events_and_the_chains_that_belong_to_them(
    session_factory: Factory,
) -> None:
    group, saved = await add_session(session_factory, id=None)
    assert group.id is not None and saved.id is not None
    bus, tasks = EventBus(), TaskSupervisor()
    writer = DBWriter(bus, session_factory, tasks)
    writer.start()

    run = make_session_run(saved.id)
    bus.publish(SessionRunChanged(occurred_at=NOW, run=run))
    chain = make_chain(group.id, session_run_id=run.id, pair_no=1, signal_id=None)
    bus.publish(ChainStarted(occurred_at=NOW, chain=chain))
    ended = replace(run, state=RunState.ENDED, end_reason=RunEndReason.WINDOW_ENDED)
    bus.publish(SessionRunChanged(occurred_at=NOW, run=ended))
    await writer.stop()
    await tasks.shutdown()

    async with session_factory() as db:
        assert await SessionRepository(db).get_run(run.id) == ended
        stored = await ChainRepository(db).get(chain.id)
    assert stored is not None and stored.session_run_id == run.id
    assert writer.stats.failed == 0


async def test_start_up_reads_the_sessions_and_the_runs_still_marked_as_going(
    session_factory: Factory,
) -> None:
    _, saved = await add_session(session_factory, id=None)
    assert saved.id is not None
    going = make_session_run(saved.id, state=RunState.RUNNING)
    stopping = make_session_run(
        saved.id, state=RunState.STOPPING, started_at=NOW - timedelta(hours=1)
    )
    ended = make_session_run(saved.id, state=RunState.ENDED)
    async with session_factory.begin() as db:
        for run in (going, stopping, ended):
            await SessionRepository(db).upsert_run(run)

    state = await load_recovery_state(session_factory)
    assert [s.id for s in state.sessions] == [saved.id]
    assert [r.id for r in state.unfinished_runs] == [stopping.id, going.id]
    assert any(g.source is GroupSource.SESSION for g in state.groups)  # the hidden group is loaded


def test_a_session_record_refuses_what_makes_no_sense() -> None:
    for bad in (
        {"name": "  "},
        {"duration_s": 0},
        {"start_time": time(11, 0), "end_time": time(11, 0)},
        {"pause_s": -1},
        {"profit_target": Decimal(0)},
        {"loss_limit": Decimal("-1")},
        {"max_pairs": 0},
        {"repeat": RepeatKind.WEEKDAYS, "weekdays": ()},
        {"weekdays": (0, 0)},
        {"weekdays": (7,)},
    ):
        with pytest.raises(ValueError):
            make_session(**bad)


async def test_the_mode_and_the_open_pair_limit_are_stored(session_factory: Factory) -> None:
    _, saved = await add_session(
        session_factory, id=None, mode=SessionMode.EVERY_CANDLE, max_open_pairs=4
    )
    assert saved.id is not None
    async with session_factory() as db:
        loaded = await SessionRepository(db).get(saved.id)
    assert loaded is not None
    assert (loaded.mode, loaded.max_open_pairs) == (SessionMode.EVERY_CANDLE, 4)
    assert make_session().mode is SessionMode.SEQUENTIAL  # the default is one pair at a time
    with pytest.raises(ValueError):
        make_session(max_open_pairs=0)
