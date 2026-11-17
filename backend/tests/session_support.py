"""Helpers for the trading-session tests: timers that move only when the test says so, and a rig
with one session (and its hidden group) already set up."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.domain.enums import AssetSuffixMode, GroupSource, RunState, Strategy
from app.domain.records import (
    ChainRecord,
    GroupRecord,
    GroupSettingsRecord,
    SessionRecord,
    SessionRunRecord,
    SignalRecord,
)
from app.engine.risk import RiskLimits
from app.events.types import ChainAdvanced, ChainEnded, ChainStarted, SessionRunChanged
from tests.engine_support import EngineRig, make_rig
from tests.factories import make_group, make_session, make_settings
from tests.signal_support import ManualClock

D = Decimal
SESSION_GROUP = 50
# a Sunday morning, one hour before the default 11:00 window
T10 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)


class FakeTimers:
    """A clock that moves only when advanced, and a `sleep` that wakes when its moment has come."""

    def __init__(self, clock: ManualClock) -> None:
        self.clock = clock
        self._waiters: list[tuple[datetime, asyncio.Future[None]]] = []

    async def sleep(self, delay: float) -> None:
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append((self.clock.now() + timedelta(seconds=delay), future))
        await future

    async def settle(self, turns: int = 80) -> None:
        for _ in range(turns):
            await asyncio.sleep(0)

    async def advance(self, seconds: float) -> None:
        """Move time forward, waking every sleeper at its own moment, in order."""
        await self.advance_to(self.clock.now() + timedelta(seconds=seconds))

    async def advance_to(self, target: datetime) -> None:
        await self.settle()
        while True:
            self._waiters = [(d, f) for d, f in self._waiters if not f.done()]
            due = [d for d, _ in self._waiters if d <= target]
            if not due:
                break
            moment = max(min(due), self.clock.now())
            self.clock.set(moment)
            for deadline, future in list(self._waiters):
                if deadline <= moment and not future.done():
                    future.set_result(None)
            await self.settle()
        self.clock.set(target)
        await self.settle()


@dataclass
class SessionRig:
    rig: EngineRig
    timers: FakeTimers
    session: SessionRecord
    settings: GroupSettingsRecord
    _latest: dict[Any, SessionRunRecord] = field(default_factory=dict)

    @property
    def engine(self) -> Any:
        return self.rig.engine

    @property
    def scheduler(self) -> Any:
        return self.rig.engine.scheduler

    @property
    def adapter(self) -> Any:
        return self.rig.adapter

    def runs(self) -> list[SessionRunRecord]:
        """The latest record of every run, in the order they started."""
        latest: dict[Any, SessionRunRecord] = {}
        for event in self.rig.collect():
            if isinstance(event, SessionRunChanged):
                latest[event.run.id] = event.run
        return sorted(latest.values(), key=lambda r: r.started_at)

    def run(self) -> SessionRunRecord:
        [run] = self.runs()
        return run

    def chains(self) -> list[ChainRecord]:
        """The latest record of every chain, in the order they started."""
        latest: dict[Any, ChainRecord] = {}
        order: list[Any] = []
        for event in self.rig.collect():
            if isinstance(event, ChainStarted | ChainAdvanced | ChainEnded):
                if event.chain.id not in latest:
                    order.append(event.chain.id)
                latest[event.chain.id] = event.chain
        return [latest[cid] for cid in order]

    def inbox(self) -> list[SignalRecord]:
        return self.rig.inbox()

    async def start(self) -> None:
        """Connect the fake brokers and start the scheduler (the way the engine does)."""
        await self.adapter.connect()
        if self.rig.deriv is not None:
            await self.rig.deriv.connect()
        if self.engine.listener is not None:
            self.engine.listener.start()
        self.engine.scheduler.start()
        await self.timers.settle()

    async def stop(self) -> None:
        await self.rig.stop()

    def settle_orders(self, *, upto: int | None = None) -> None:
        """Release every order that is held (the first `upto` of them if given)."""
        for order in self.adapter.orders[:upto]:
            self.adapter.settle(order.order_id)


def make_session_rig(
    *,
    session: SessionRecord | None = None,
    strategy: Strategy = Strategy.FLIP_EVERY_LOSS,
    base: str = "1.00",
    multipliers: tuple[str, ...] = ("2.0", "3.0"),
    min_payout_pct: int = 0,
    now: datetime = T10,
    hold_results: bool = True,
    with_telegram: bool = True,
    limits: RiskLimits | None = None,
    with_deriv: bool = False,
    **session_overrides: Any,
) -> SessionRig:
    clock = ManualClock(now)
    timers = FakeTimers(clock)
    rig = make_rig(
        clock=clock,
        hold_results=hold_results,
        session_sleep=timers.sleep,
        with_telegram=with_telegram,
        limits=limits,
        with_deriv=with_deriv,
    )
    group: GroupRecord = replace(
        make_group(telegram_chat_id=None, title="Session: Test", source=GroupSource.SESSION),
        id=SESSION_GROUP,
    )
    settings = make_settings(
        SESSION_GROUP,
        parser="session",
        asset_suffix_mode=AssetSuffixMode.NONE,
        timezone="UTC",
        strategy=strategy,
        base_stake=D(base),
        max_steps=len(multipliers),
        multipliers=tuple(D(m) for m in multipliers),
        min_payout_pct=min_payout_pct,
    )
    record = session or make_session(group_id=SESSION_GROUP, once_after=now, **session_overrides)
    group = replace(group, broker=record.broker)  # the hidden group trades where the session does
    rig.engine.set_group(group, settings)
    rig.engine.set_session(record, settings)
    return SessionRig(rig, timers, record, settings)


def is_running(run: SessionRunRecord) -> bool:
    return run.state is RunState.RUNNING
