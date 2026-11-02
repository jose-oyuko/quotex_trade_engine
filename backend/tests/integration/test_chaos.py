"""Chaos: the whole engine under a storm of random trouble, with a real database behind it.

Each seed plays a different mix of signals (good, duplicated, unreadable, for unknown assets), order
refusals, lost confirmations, Quotex connection drops, closed assets, results held back, kill switch
and pause toggles, group edits mid-chain and a database that goes away and comes back. When the dust
settles - everything restored, everything settled - the books must balance. The checks are the ones
that matter with money: nothing left half-done, nothing duplicated, nothing stored that never
happened, nothing that happened but is not stored, and the safety switches obeyed.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal
from random import Random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.recovery import load_recovery_state
from app.db.repositories import ChainRepository, GroupRepository, SignalRepository, TradeRepository
from app.db.writer import DBWriter
from app.domain.enums import (
    RESULT_TRADE_STATUSES,
    AccountType,
    AssetSuffixMode,
    ChainStatus,
    SignalStatus,
    Strategy,
    TradeStatus,
)
from app.engine.risk import RiskLimits
from app.engine.strategies import step_stake
from app.events.types import ChainEnded, Event
from app.quotex.base import TradeOutcome
from app.quotex.errors import (
    AssetClosedError,
    OrderAckTimeoutError,
    OrderRejectedError,
    QuotexError,
)
from app.services.live import LiveState
from tests.engine_support import EngineRig, make_rig
from tests.factories import make_group, make_settings
from tests.integration.test_writer_outage import FlakyFactory
from tests.signal_support import ManualClock

Factory = async_sessionmaker[AsyncSession]
D = Decimal
ASSETS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD")
STRATEGIES = (
    Strategy.MARTINGALE,
    Strategy.FLIP_EVERY_LOSS,
    Strategy.NO_MARTINGALE,
    Strategy.TWO_STEP_FLIP,
)
CHATS = {1: -1001, 2: -1002, 3: -1003, 4: -1004}
ERRORS: tuple[QuotexError, ...] = (
    OrderRejectedError("fake: Quotex refused the order"),
    OrderAckTimeoutError("fake: no confirmation arrived"),
    AssetClosedError("fake: the asset closed"),
)


async def fast_sleep(_: float) -> None:
    await asyncio.sleep(0)


async def store_groups(factory: Factory) -> None:
    async with factory.begin() as session:
        repo = GroupRepository(session)
        for number, strategy in enumerate(STRATEGIES, start=1):
            group = await repo.add(
                make_group(telegram_chat_id=CHATS[number], title=f"group {number}")
            )
            assert group.id == number
            steps = 0 if strategy is Strategy.NO_MARTINGALE else 3
            await repo.save_settings(
                make_settings(
                    number,
                    strategy=strategy,
                    base_stake=D("1.00"),
                    max_steps=steps,
                    multipliers=(D("2.0"), D("2.5"), D("3.0"))[:steps],
                    asset_suffix_mode=AssetSuffixMode.NONE,
                    timezone="UTC",
                    min_payout_pct=0,
                )
            )


class Storm:
    """One random run. `play` applies random events; `calm_down` restores everything."""

    def __init__(self, rig: EngineRig, flaky: FlakyFactory, rng: Random) -> None:
        self.rig, self.flaky, self.rng = rig, flaky, rng
        self.sent = 0
        self.kill_marks: list[int] = []  # orders placed when the kill switch went on
        self.violations: list[str] = []

    @property
    def manager(self):  # type: ignore[no-untyped-def]
        return self.rig.engine.manager

    async def play(self, actions: int) -> None:
        for _ in range(actions):
            await self._one()
            for _ in range(self.rng.randint(0, 3)):
                await asyncio.sleep(0)

    async def _one(self) -> None:
        rng, adapter = self.rng, self.rig.adapter
        roll = rng.random()
        if roll < 0.52:
            self._signal()
        elif roll < 0.60:
            adapter.fail_next_order(rng.choice(ERRORS))
        elif roll < 0.65:
            adapter.simulate_connection_loss()
        elif roll < 0.72:
            adapter.simulate_connection_restored()
        elif roll < 0.76:
            adapter.set_open(rng.choice(ASSETS), rng.random() < 0.5)
        elif roll < 0.80:
            adapter.hold_results = not adapter.hold_results
            if not adapter.hold_results:
                adapter.settle_all()
        elif roll < 0.84:
            self._kill_switch()
        elif roll < 0.88:
            group = rng.randint(1, 4)
            if rng.random() < 0.5:
                self.manager.pause_group(group)
            else:
                self.manager.resume_group(group)
        elif roll < 0.92:
            self._edit_group()
        elif roll < 0.96:
            self.flaky.down = not self.flaky.down  # the database goes away, or comes back
        else:  # a quiet moment: let everything that can run, run
            for _ in range(10):
                await asyncio.sleep(0)

    def _signal(self) -> None:
        rng, rig = self.rng, self.rig
        group = rng.randint(1, 4)
        kind = rng.random()
        if kind < 0.10:
            text = "good morning everyone, big day ahead"
        elif kind < 0.15:
            text = "EURUSD sometime today maybe"  # no direction: not a signal
        else:
            asset = rng.choice((*ASSETS, "FOOBAR"))  # FOOBAR: unknown to the broker
            text = f"{asset} {rng.choice(('CALL', 'PUT'))} {rng.choice((15, 30, 60))}s"
        rig.adapter.script_results(
            *[rng.choice((TradeOutcome.WON, TradeOutcome.LOST)) for _ in range(rng.randint(1, 3))]
        )
        rig.signal(CHATS[group], text)
        self.sent += 1
        if rng.random() < 0.15:  # the same message delivered twice: it must be traded once
            rig.source.emit(CHATS[group], text, message_id=rig._message_id)

    def _kill_switch(self) -> None:
        manager = self.manager
        if self.rig.engine.guard.kill_switch:
            self.violations.extend(self._check_kill_window())
            manager.release_kill_switch()
        else:
            self.kill_marks.append(len(self.rig.adapter.orders))
            manager.engage_kill_switch(stop_chains=self.rng.random() < 0.5)

    def _check_kill_window(self) -> list[str]:
        placed = len(self.rig.adapter.orders) - self.kill_marks[-1]
        return [f"{placed} order(s) went out while the kill switch was on"] if placed else []

    def _edit_group(self) -> None:
        group_number = self.rng.randint(1, 4)
        # changing a group's stake mid-run must never change the chains already running (D-10)
        settings = make_settings(
            group_number,
            strategy=STRATEGIES[group_number - 1],
            base_stake=D(self.rng.choice(("1.00", "2.00", "0.50"))),
            max_steps=0 if STRATEGIES[group_number - 1] is Strategy.NO_MARTINGALE else 3,
            multipliers=()
            if STRATEGIES[group_number - 1] is Strategy.NO_MARTINGALE
            else (D("2.0"), D("2.5"), D("3.0")),
            asset_suffix_mode=AssetSuffixMode.NONE,
            timezone="UTC",
            min_payout_pct=0,
        )
        group = make_group(telegram_chat_id=CHATS[group_number], title=f"group {group_number}")
        self.rig.engine.set_group(replace(group, id=group_number), settings)

    async def calm_down(self) -> None:
        adapter = self.rig.adapter
        if self.rig.engine.guard.kill_switch:
            self.violations.extend(self._check_kill_window())
            self.manager.release_kill_switch()
        adapter.simulate_connection_restored()
        for asset in ASSETS:
            adapter.set_open(asset, True)
        adapter.hold_results = False
        self.flaky.down = False
        for _ in range(5):
            adapter.settle_all()
            await asyncio.sleep(0)
        await self.rig.idle()


@pytest.mark.parametrize("seed", range(14))
async def test_the_books_balance_after_a_storm(session_factory: Factory, seed: int) -> None:
    await store_groups(session_factory)
    flaky = FlakyFactory(session_factory)
    rig = make_rig(clock=ManualClock(), limits=RiskLimits())
    writer = DBWriter(
        rig.bus,
        flaky,  # type: ignore[arg-type]
        rig.tasks,
        sleep=fast_sleep,
        rng=lambda: 0.5,
    )
    writer.start()
    rig.engine.load(await load_recovery_state(session_factory))
    await rig.start()
    live, feed = LiveState(), rig.bus.subscribe(name="chaos-live", maxsize=1_000_000)
    ended: list[Event] = []
    history: list[Event] = []

    storm = Storm(rig, flaky, Random(seed))  # noqa: S311
    await storm.play(90)
    await storm.calm_down()
    while (event := feed.get_nowait()) is not None:
        live.apply(event)
        history.append(event)
        if isinstance(event, ChainEnded):
            ended.append(event)
    await rig.stop(writer)

    async with session_factory() as session:
        chains = await ChainRepository(session).list(limit=1000)
        trades = await TradeRepository(session).list(limit=1000)
        signals = await SignalRepository(session).list(limit=1000)
    chain_by_id = {c.id: c for c in chains}

    # 1. Nothing is left half-done: every chain and trade reached an end.
    stuck = [c for c in chains if c.status in (ChainStatus.PENDING, ChainStatus.OPEN)]
    trail = (
        [
            (e.name, getattr(e, "chain", None) and e.chain.status.value)  # type: ignore[attr-defined]
            for e in history
            if getattr(getattr(e, "chain", None), "id", None) == stuck[0].id
        ]
        if stuck
        else []
    )
    assert stuck == [], (seed, trail)  # the trail shows the order events reached the database
    assert [t for t in trades if t.status in (TradeStatus.PENDING, TradeStatus.OPEN)] == []
    assert live.chains == {} and live.trades == {}  # and the live picture agrees
    assert rig.engine.manager.active_chains() == []

    # 2. What the broker saw and what we stored are the same orders.
    stored_orders = {t.broker_order_id for t in trades if t.broker_order_id}
    assert stored_orders == {o.order_id for o in rig.adapter.orders}
    assert len(stored_orders) == len([t for t in trades if t.broker_order_id])  # none twice

    # 3. The risk guard has nothing reserved, and today's result equals the stored profits.
    guard = rig.engine.guard
    assert guard.open_trades == 0 and guard.open_exposure == D(0)
    resolved = [t for t in trades if t.status in RESULT_TRADE_STATUSES and t.profit is not None]
    assert guard.day_pnl(AccountType.DEMO) == sum((t.profit or D(0) for t in resolved), D(0))

    # 4. Every chain is a clean sequence of steps with the stakes its own settings dictate.
    steps_by_chain: dict[object, list[int]] = {}
    for t in trades:
        steps_by_chain.setdefault(t.chain_id, []).append(t.step)
        chain = chain_by_id[t.chain_id]
        assert t.stake == step_stake(t.step, chain.base_stake, chain.multipliers), (seed, t.id)
    for chain_id, steps in steps_by_chain.items():
        assert sorted(steps) == list(range(len(steps))), (seed, chain_id, steps)  # 0,1,2... no gaps
    for chain in chains:
        assert len(steps_by_chain.get(chain.id, [])) <= chain.max_steps + 1  # never past the limit

    # 5. Every chain came from exactly one parsed message, and no message started two chains.
    parsed = {s.id for s in signals if s.status is SignalStatus.PARSED}
    started_from = [c.signal_id for c in chains]
    assert len(started_from) == len(set(started_from))
    assert set(started_from) <= parsed
    assert parsed <= set(started_from)  # a parsed message that is not ignored always has its chain

    # 6. The safety switches were obeyed, and nothing crashed inside the engine.
    assert storm.violations == []
    assert [e for e in ended if (e.chain.end_reason or "").startswith("internal error")] == []

    # 7. The database outages cost nothing: no record failed or was dropped.
    assert writer.stats.failed == 0 and writer.dropped == 0, (writer.stats, writer.dropped)
    assert storm.sent > 10  # the run really did something


async def test_ending_a_chain_in_the_moment_it_starts_keeps_the_events_in_order(
    session_factory: Factory,
) -> None:
    """The bug the storm found: the owner ends a chain (kill switch, "skip to base") in the same
    event-loop turn it was created. Its `ended` used to reach the database before its `started`, and
    the older `pending` row then overwrote `stopped` for good."""
    await store_groups(session_factory)
    for how in ("kill_switch", "end_chain"):
        rig = make_rig(clock=ManualClock(), limits=RiskLimits(), hold_results=True)
        writer = DBWriter(rig.bus, session_factory, rig.tasks)
        writer.start()
        rig.engine.load(await load_recovery_state(session_factory))
        await rig.start()

        rig.signal(CHATS[1], "EURUSD CALL 1m")
        if how == "kill_switch":
            rig.engine.manager.engage_kill_switch(stop_chains=True)
        else:
            rig.engine.manager.end_chain(rig.engine.manager.active_chains()[0].id)
        await rig.idle()
        names = [e.name for e in rig.collect() if e.name.startswith("chain.")]
        assert names == ["chain.started", "chain.ended"], (how, names)
        await rig.stop(writer)

        async with session_factory() as session:
            chains = await ChainRepository(session).list(limit=10)
        assert chains[0].status is ChainStatus.STOPPED, how
        assert chains[0].ended_at is not None
        async with session_factory.begin() as session:  # a clean slate for the second variant
            from sqlalchemy import delete

            from app.db.models import AppSetting, Chain, Signal, Trade

            # the kill switch of the first variant was stored too, and would greet the second
            for table in (Trade, Chain, Signal, AppSetting):
                await session.execute(delete(table))
