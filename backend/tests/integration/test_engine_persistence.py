"""The engine with the real database writer behind it: what is stored, and what a restart does."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.recovery import RecoveryState, load_recovery_state
from app.db.repositories import (
    ChainRepository,
    GroupRepository,
    RiskEventRepository,
    SignalRepository,
    TradeRepository,
)
from app.db.writer import DBWriter
from app.domain.enums import AssetSuffixMode, ChainStatus, SignalStatus, Strategy, TradeStatus
from app.engine.manager import RESTART_REASON
from app.quotex.base import TradeOutcome
from tests.engine_support import EngineRig, GroupSpec, make_rig
from tests.factories import NOW, make_chain, make_group, make_settings, make_trade
from tests.signal_support import ManualClock

Factory = async_sessionmaker[AsyncSession]
D = Decimal
FLIP = GroupSpec(1, -1001, Strategy.FLIP_EVERY_LOSS, "1.00", ("2.0", "3.0"))


async def add_flip_group(session_factory: Factory) -> int:
    async with session_factory.begin() as session:
        repo = GroupRepository(session)
        group = await repo.add(make_group(telegram_chat_id=FLIP.chat_id, title="flip"))
        assert group.id is not None
        await repo.save_settings(
            make_settings(
                group.id,
                strategy=FLIP.strategy,
                base_stake=D(FLIP.base),
                max_steps=2,
                multipliers=(D("2.0"), D("3.0")),
                asset_suffix_mode=AssetSuffixMode.NONE,
                timezone="UTC",
            )
        )
        return group.id


def start_writer(rig: EngineRig, session_factory: Factory) -> DBWriter:
    writer = DBWriter(rig.bus, session_factory, rig.tasks)
    writer.start()
    return writer


async def test_a_run_ends_up_in_the_database_exactly_as_it_happened(
    session_factory: Factory,
) -> None:
    group_id = await add_flip_group(session_factory)
    rig = make_rig(hold_results=True)
    writer = start_writer(rig, session_factory)
    rig.engine.load(await load_recovery_state(session_factory))
    await rig.start()
    rig.adapter.script_results(TradeOutcome.LOST, TradeOutcome.WON)

    rig.signal(FLIP.chat_id, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)
    rig.signal(FLIP.chat_id, "GBPUSD PUT 1m")  # ignored: the flip chain is running
    rig.settle_last("EURUSD")
    await rig.until(lambda: len(rig.adapter.orders) == 2)
    rig.settle_last("EURUSD")
    await rig.idle()
    await rig.stop(writer)

    async with session_factory() as session:
        chains = await ChainRepository(session).list(group_id=group_id)
        [chain] = chains
        trades = await TradeRepository(session).list_for_chain(chain.id)
        inbox = {r.asset: r for r in await SignalRepository(session).list(group_id=group_id)}
    assert (chain.status, chain.step, chain.consecutive_losses) == (ChainStatus.COMPLETED, 1, 1)
    assert [(t.step, t.status, t.stake, t.direction.value) for t in trades] == [
        (0, TradeStatus.LOST, D("1.00"), "call"),
        (1, TradeStatus.WON, D("2.00"), "put"),
    ]
    assert trades[0].t_msg_received_ns is not None and trades[0].t_order_acked_ns is not None
    assert inbox["EURUSD"].status is SignalStatus.PARSED
    # The ignored signal's row must END as ignored although "parsed" was published after it was
    # handed over: the update is ordered after the pipeline's row.
    assert inbox["GBPUSD"].status is SignalStatus.IGNORED
    assert inbox["GBPUSD"].reason is not None and inbox["GBPUSD"].reason.startswith("chain active")
    assert writer.stats.failed == 0


async def test_restart_mid_chain_marks_everything_in_flight_unknown_and_frees_the_group(
    session_factory: Factory,
) -> None:
    group_id = await add_flip_group(session_factory)
    other_group = await add_flip_group_two(session_factory)
    # What the database looked like when the application died:
    open_chain = make_chain(group_id, asset="EURUSD", status=ChainStatus.OPEN, step=1)
    between_steps = make_chain(other_group, asset="GBPUSD", status=ChainStatus.OPEN, step=1)
    async with session_factory.begin() as session:
        chains, trades = ChainRepository(session), TradeRepository(session)
        await chains.upsert(open_chain)
        await chains.upsert(between_steps)
        await trades.upsert(
            make_trade(open_chain.id, group_id, step=0, status=TradeStatus.LOST, profit=D("-1.00"))
        )
        await trades.upsert(
            make_trade(
                open_chain.id, group_id, step=1, status=TradeStatus.OPEN, broker_order_id="b1"
            )
        )
        await trades.upsert(  # the order may or may not have reached Quotex
            make_trade(between_steps.id, other_group, step=1, status=TradeStatus.PENDING)
        )
        await trades.upsert(
            make_trade(between_steps.id, other_group, step=0, status=TradeStatus.LOST)
        )

    rig = make_rig()
    writer = start_writer(rig, session_factory)
    summary = rig.engine.load(await load_recovery_state(session_factory))
    assert (summary.chains_marked_unknown, summary.trades_marked_unknown) == (2, 2)
    await rig.start()

    # the group is free again at once: a new signal trades
    rig.signal(FLIP.chat_id, "USDJPY CALL 1m")
    await rig.idle()
    assert len(rig.adapter.orders) == 1
    await rig.stop(writer)

    async with session_factory() as session:
        for chain_id in (open_chain.id, between_steps.id):
            stored = await ChainRepository(session).get(chain_id)
            assert stored is not None
            assert stored.status is ChainStatus.UNKNOWN and stored.end_reason == RESTART_REASON
            assert stored.ended_at is not None
        by_step = {
            (t.group_id, t.step): t for t in await _all_trades(session, [open_chain, between_steps])
        }
        assert by_step[(group_id, 0)].status is TradeStatus.LOST  # known results are not touched
        assert by_step[(group_id, 1)].status is TradeStatus.UNKNOWN
        assert by_step[(other_group, 1)].status is TradeStatus.UNKNOWN
        assert by_step[(other_group, 0)].status is TradeStatus.LOST
        assert by_step[(group_id, 1)].error == RESTART_REASON
        assert await ChainRepository(session).list_open() == []  # nothing is left "open"
        alerts = await RiskEventRepository(session).list_recent()
    assert sorted(a.kind for a in alerts) == ["restart_unknown", "restart_unknown"]
    assert {a.group_id for a in alerts} == {group_id, other_group}


async def add_flip_group_two(session_factory: Factory) -> int:
    async with session_factory.begin() as session:
        repo = GroupRepository(session)
        group = await repo.add(make_group(telegram_chat_id=-1002, title="second"))
        assert group.id is not None
        await repo.save_settings(
            make_settings(
                group.id,
                strategy=Strategy.MARTINGALE,
                asset_suffix_mode=AssetSuffixMode.NONE,
                timezone="UTC",
            )
        )
        return group.id


async def _all_trades(session: AsyncSession, chains: list) -> list:  # type: ignore[type-arg]
    found = []
    for chain in chains:
        found.extend(await TradeRepository(session).list_for_chain(chain.id))
    return found


async def test_recovery_with_nothing_in_flight_does_nothing() -> None:
    rig = make_rig()
    summary = rig.engine.load(RecoveryState([], [], [], []))
    assert (summary.chains_marked_unknown, summary.trades_marked_unknown) == (0, 0)
    assert rig.collect() == []


async def test_recovered_rows_keep_their_times_sensible() -> None:
    """A trade flagged unknown is stamped as ended at recovery time, after it was created."""
    rig = make_rig(clock=ManualClock(NOW + timedelta(hours=1)))
    chain = make_chain(1, status=ChainStatus.OPEN)
    trade = replace(make_trade(chain.id, 1), created_at=NOW - timedelta(minutes=5))
    rig.engine.load(RecoveryState([], [], [chain], [trade]))
    settled = [e for e in rig.collect() if e.name == "trade.settled"]
    assert len(settled) == 1
    assert settled[0].trade.settled_at is not None  # type: ignore[attr-defined]
    assert settled[0].trade.settled_at > settled[0].trade.created_at  # type: ignore[attr-defined]
