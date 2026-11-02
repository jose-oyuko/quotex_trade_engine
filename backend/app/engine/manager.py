"""ChainManager: turns signals into chains and drives each chain to its end.

Each chain runs in its own supervised task, so a slow chain never delays another, and chains share
nothing: the loss counter, step and direction live in the chain (decision D-10). The manager only
owns the registry of running chains, the group settings in memory, and decision D-9.

A signal is handled synchronously (`on_signal` never waits): it creates the chain in memory,
publishes `chain.started` and starts the task. The task's first act is the order. Nothing here
touches the database; every change is an event for the DB writer.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, replace
from uuid import UUID

import structlog

from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.db.recovery import RecoveryState
from app.domain.enums import ChainStatus, SignalStatus, TradeStatus
from app.domain.ids import new_id
from app.domain.records import GroupSettingsRecord, RiskEventRecord, SignalRecord
from app.engine.chain import Chain, ChainSpec
from app.engine.errors import UnknownChainError
from app.engine.executor import Executor, PlacedTrade, Stamps, StepKind, StepOutcome
from app.engine.risk import RiskGuard
from app.engine.strategies import FLIP_STRATEGIES, StepPlan
from app.events.bus import EventBus
from app.events.types import (
    ChainAdvanced,
    ChainEnded,
    ChainStarted,
    Event,
    RiskTripped,
    SignalReceived,
    TradeSettled,
)
from app.quotex.base import TradeOutcome
from app.signals.models import Signal

log = structlog.get_logger()

RESTART_REASON = "the application stopped while this was in progress; the outcome is unknown"


@dataclass(slots=True, frozen=True)
class RecoverySummary:
    chains_marked_unknown: int
    trades_marked_unknown: int


_KIND_OUTCOME = {
    StepKind.WON: TradeOutcome.WON,
    StepKind.LOST: TradeOutcome.LOST,
    StepKind.DRAW: TradeOutcome.DRAW,
}


class ChainManager:
    def __init__(
        self,
        *,
        executor: Executor,
        guard: RiskGuard,
        bus: EventBus,
        clock: Clock,
        tasks: TaskSupervisor,
    ) -> None:
        self._executor = executor
        self._guard = guard
        self._bus = bus
        self._clock = clock
        self._tasks = tasks
        self._settings: dict[int, GroupSettingsRecord] = {}
        self._chains: dict[UUID, Chain] = {}
        self._by_group: defaultdict[int, set[UUID]] = defaultdict(set)
        self._drivers: dict[UUID, asyncio.Task[None]] = {}

    # --- group settings (in memory; updated when a group is edited) ---

    def set_group(self, settings: GroupSettingsRecord) -> None:
        """New settings apply to chains created from now on; running chains keep theirs."""
        self._settings[settings.group_id] = settings

    def remove_group(self, group_id: int) -> None:
        self._settings.pop(group_id, None)

    # --- queries ---

    def active_chains(self, group_id: int | None = None) -> list[Chain]:
        if group_id is None:
            return list(self._chains.values())
        return [self._chains[cid] for cid in self._by_group.get(group_id, ())]

    async def stop(self) -> None:
        """Cancel every running chain. Their open trades stay open in the database; the next
        start flags them `unknown` (recovery), which is the truth: we stopped watching them."""
        drivers = list(self._drivers.values())
        for driver in drivers:
            driver.cancel()
        if drivers:
            await asyncio.gather(*drivers, return_exceptions=True)

    async def wait_idle(self, timeout_s: float | None = None) -> None:
        """Wait until every running chain has ended (used by tests and orderly shutdown)."""
        drivers = list(self._drivers.values())
        if drivers:
            async with asyncio.timeout(timeout_s):
                await asyncio.gather(*drivers, return_exceptions=True)

    # --- signals in ---

    def on_signal(self, signal: Signal) -> None:
        if (blocked := self._guard.signal_block_reason(signal.group_id)) is not None:
            self._ignore(signal, blocked)
            return
        settings = self._settings.get(signal.group_id)
        if settings is None:
            self._ignore(signal, "group has no strategy settings")
            return
        if settings.strategy in FLIP_STRATEGIES and (
            running := self.active_chains(signal.group_id)
        ):
            self._ignore(
                signal,
                f"chain active: {settings.strategy.value} ignores new signals until chain "
                f"{running[0].id} ends",
            )
            return
        decided_ns = self._clock.monotonic_ns()
        now = self._clock.now()
        chain = Chain(
            ChainSpec(
                id=new_id(),
                group_id=signal.group_id,
                signal_id=signal.id,
                asset=signal.asset,
                origin_direction=signal.direction,
                duration_s=signal.duration_s,
                account_type=self._executor.account_type,
                strategy=settings.strategy,
                base_stake=settings.base_stake,
                multipliers=settings.multipliers,
                max_steps=settings.max_steps,
                min_payout_pct=settings.min_payout_pct,
            ),
            now,
        )
        try:
            plan = chain.plan()
        except ValueError as exc:
            self._ignore(signal, f"cannot plan the first trade: {exc}")
            return
        self._register(chain)
        # Not published here: the chain row points at the signal's inbox row, which the pipeline
        # publishes only after handing the signal over (see `_publish_after_inbox_row`). The
        # driver task is created after this call, so it still starts after the event.
        self._publish_after_inbox_row(ChainStarted(occurred_at=now, chain=chain.to_record()))
        stamps = Stamps(signal.t_msg_received_ns, signal.t_parsed_ns, decided_ns)
        self._drivers[chain.id] = self._tasks.spawn(
            self._drive(chain, plan, stamps), name=f"chain-{chain.id}"
        )

    def _ignore(self, signal: Signal, reason: str) -> None:
        """Replace the signal's inbox row (same id) with an 'ignored' one that says why."""
        record = SignalRecord(
            id=signal.id,
            group_id=signal.group_id,
            telegram_message_id=signal.telegram_message_id,
            received_at=signal.received_at,
            raw_text=signal.raw_text,
            status=SignalStatus.IGNORED,
            reason=reason,
            asset=signal.asset,
            direction=signal.direction,
            duration_s=signal.duration_s,
            entry_time=signal.entry_at,
        )
        self._publish_after_inbox_row(SignalReceived(occurred_at=self._clock.now(), signal=record))

    def _publish_after_inbox_row(self, event: Event) -> None:
        """The pipeline hands us a signal *before* it publishes the signal's "parsed" inbox row
        (so the order never waits for bookkeeping). Anything that refers to that row, or replaces
        it, must reach the database after it: a chain row has a foreign key to it, and an "ignored"
        update would otherwise be overwritten by "parsed". The next turn of the event loop is
        after the pipeline's synchronous publish and before any task created from here on."""
        asyncio.get_running_loop().call_soon(self._bus.publish, event)

    # --- driving a chain ---

    async def _drive(self, chain: Chain, plan: StepPlan, stamps: Stamps) -> None:
        try:
            while chain.active:
                placed = await self._executor.place(chain, plan, stamps)
                if isinstance(placed, PlacedTrade):
                    if chain.status is ChainStatus.PENDING:
                        chain.mark_open(self._clock.now())
                        self._bus.publish(
                            ChainAdvanced(occurred_at=self._clock.now(), chain=chain.to_record())
                        )
                    outcome = await self._executor.settle(placed)
                else:
                    outcome = placed
                if not chain.active:
                    return  # the owner ended the chain while this trade was open; it is recorded
                next_plan = self._apply(chain, outcome)
                if next_plan is None:
                    return
                # A follow-up goes out the moment the loss is known: the only work in between is
                # this bookkeeping, all in memory.
                plan = next_plan
                stamps = Stamps(None, None, self._clock.monotonic_ns())
        except asyncio.CancelledError:
            raise  # shutdown: the trade stays open in the database and recovery will flag it
        except Exception as exc:
            log.exception("chain_crashed", chain_id=str(chain.id))
            if chain.active:
                chain.mark_unknown(
                    f"internal error: {type(exc).__name__}: {exc}", self._clock.now()
                )
                self._bus.publish(
                    ChainEnded(occurred_at=self._clock.now(), chain=chain.to_record())
                )
        finally:
            self._release(chain)

    def _apply(self, chain: Chain, outcome: StepOutcome) -> StepPlan | None:
        now = self._clock.now()
        next_plan: StepPlan | None = None
        if outcome.kind is StepKind.BLOCKED and outcome.stop:
            chain.stop(outcome.detail or "kill switch engaged", now)
        elif outcome.kind in (StepKind.FAILED, StepKind.BLOCKED):
            chain.fail(outcome.detail or "order refused", now)
        elif outcome.kind is StepKind.UNKNOWN:
            chain.mark_unknown(outcome.detail or "outcome unknown", now)
        else:
            next_plan = chain.apply_result(_KIND_OUTCOME[outcome.kind], now)
        event_type = ChainAdvanced if chain.active else ChainEnded
        self._bus.publish(event_type(occurred_at=now, chain=chain.to_record()))
        return next_plan

    # --- the owner's controls (the API of Phase 6 calls these) ---

    def pause_group(self, group_id: int) -> None:
        """New signals of the group are ignored (and say so); its running chains finish."""
        self._guard.pause_group(group_id)

    def resume_group(self, group_id: int) -> None:
        self._guard.resume_group(group_id)

    def engage_kill_switch(self, *, stop_chains: bool = False) -> None:
        """No order goes out from now on, follow-ups included. Running chains end as `stopped`
        when their next order is refused; with `stop_chains` they end right now, and their open
        trades are still recorded when they settle."""
        self._guard.engage_kill_switch()
        if stop_chains:
            for chain in list(self._chains.values()):
                self._stop_now(chain, "kill switch engaged: chain stopped")

    def release_kill_switch(self) -> None:
        self._guard.release_kill_switch()

    def stop_after_current(self, chain_id: UUID) -> None:
        """Let the trade that is open settle, then end the chain without a further step."""
        self._running(chain_id).request_stop()

    def end_chain(self, chain_id: UUID, reason: str = "ended by the owner") -> None:
        """End the chain at once (the group is free for new signals); an open trade still settles
        and is recorded, but nothing follows it."""
        self._stop_now(self._running(chain_id), reason)

    def running_chain(self, chain_id: UUID) -> Chain:
        """The running chain, or `UnknownChainError` if there is none with that id."""
        return self._running(chain_id)

    def _running(self, chain_id: UUID) -> Chain:
        chain = self._chains.get(chain_id)
        if chain is None:
            raise UnknownChainError(f"no running chain {chain_id}")
        return chain

    def _stop_now(self, chain: Chain, reason: str) -> None:
        if not chain.active:
            return
        chain.stop(reason, self._clock.now())
        self._bus.publish(ChainEnded(occurred_at=self._clock.now(), chain=chain.to_record()))
        self._unregister(chain)

    def _register(self, chain: Chain) -> None:
        self._chains[chain.id] = chain
        self._by_group[chain.group_id].add(chain.id)

    def _unregister(self, chain: Chain) -> None:
        self._chains.pop(chain.id, None)
        self._by_group[chain.group_id].discard(chain.id)

    def _release(self, chain: Chain) -> None:
        self._unregister(chain)
        self._drivers.pop(chain.id, None)

    # --- startup recovery ---

    def recover(self, state: RecoveryState) -> RecoverySummary:
        """Deal with what was in flight when the application stopped.

        We cannot see Quotex's history, and a follow-up placed minutes late is not the trade the
        strategy asked for, so everything unfinished is marked `unknown`, loudly (a `risk.tripped`
        event per affected group) and never continued or retried (decision D-35).
        """
        now = self._clock.now()
        trades = 0
        for trade in state.unsettled_trades:
            ended = replace(trade, status=TradeStatus.UNKNOWN, error=RESTART_REASON, settled_at=now)
            self._bus.publish(TradeSettled(occurred_at=now, trade=ended))
            trades += 1
        affected: dict[int, int] = defaultdict(int)
        for chain in state.open_chains:
            ended_chain = replace(
                chain,
                status=ChainStatus.UNKNOWN,
                end_reason=RESTART_REASON,
                ended_at=now,
                updated_at=now,
            )
            self._bus.publish(ChainEnded(occurred_at=now, chain=ended_chain))
            affected[chain.group_id] += 1
        for group_id, count in affected.items():
            self._bus.publish(
                RiskTripped(
                    occurred_at=now,
                    risk_event=RiskEventRecord(
                        id=new_id(),
                        occurred_at=now,
                        kind="restart_unknown",
                        message=f"{count} chain(s) were running when the application stopped "
                        "and were marked unknown: check them on Quotex",
                        group_id=group_id,
                    ),
                )
            )
        return RecoverySummary(sum(affected.values()), trades)
