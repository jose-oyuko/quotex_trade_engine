"""ChainManager: turns signals into chains and drives each chain to its end.

Each chain runs in its own supervised task, so a slow chain never delays another, and chains share
nothing: the loss counter, step and direction live in the chain (decision D-10). The manager only
owns the registry of running chains, the group settings in memory, and decision D-9.

A flip group runs one chain at a time (decision D-9), or, when its owner allows the opposite pair
(D-70), two: the second must be the opposite direction on the same asset, and nothing more. The
chains of a trading session (D-71) come in through `open_session_chain` instead: the session
scheduler decides how many pairs run, so D-9 is not applied to them.

Each group trades on its own broker (decision D-75). A signal is skipped, with the reason in the
inbox, when that broker has no login, is not connected, or would surely refuse the order (an asset
it does not trade, a trade length it does not offer): all read from memory.

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

from app.brokers.base import TradeOutcome
from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.db.recovery import RecoveryState
from app.domain.enums import Broker, ChainStatus, SignalStatus, TradeStatus
from app.domain.ids import new_id
from app.domain.records import GroupSettingsRecord, RiskEventRecord, SignalRecord
from app.engine.chain import Chain, ChainSpec
from app.engine.errors import UnknownChainError
from app.engine.executor import Executor, PlacedTrade, Stamps, StepKind, StepOutcome
from app.engine.risk import RiskGuard
from app.engine.strategies import FLIP_STRATEGIES, StepPlan, flipped
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


def _pair_refusal(
    settings: GroupSettingsRecord, signal: Signal, running: list[Chain]
) -> str | None:
    """Why a flip group may not start another chain for `signal` while `running` is going, or None
    when it may (the opposite direction on the same asset, next to a single running chain)."""
    strategy, first = settings.strategy.value, running[0]
    if not settings.allow_opposite_pair:
        return f"chain active: {strategy} ignores new signals until chain {first.id} ends"
    if len(running) > 1:
        return (
            f"chain active: {strategy} already runs a pair of chains; new signals wait until "
            "one of them ends"
        )
    origin = first.spec
    if origin.asset != signal.asset or origin.origin_direction is not flipped(signal.direction):
        return (
            f"chain active: {strategy} takes a second signal only for the opposite direction on "
            f"the same asset ({origin.asset} {origin.origin_direction.value} is running); it "
            f"waits until chain {first.id} ends"
        )
    return None


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
        self._brokers: dict[int, Broker] = {}  # each group's broker
        self._chains: dict[UUID, Chain] = {}
        self._by_group: defaultdict[int, set[UUID]] = defaultdict(set)
        self._drivers: dict[UUID, asyncio.Task[None]] = {}
        # The chain each pair member started next to, and when its first order was sent (only used
        # to log how far apart the two orders of a pair went out)
        self._partner: dict[UUID, UUID] = {}
        self._first_sent_ns: dict[UUID, int] = {}
        # `chain.started` events waiting for the signal's inbox row to be published first
        self._unannounced: dict[UUID, ChainStarted] = {}

    # --- group settings (in memory; updated when a group is edited) ---

    def set_group(self, settings: GroupSettingsRecord, broker: Broker = Broker.QUOTEX) -> None:
        """New settings (and broker) apply to chains created from now on; running chains keep
        theirs."""
        self._settings[settings.group_id] = settings
        self._brokers[settings.group_id] = broker

    def remove_group(self, group_id: int) -> None:
        self._settings.pop(group_id, None)
        self._brokers.pop(group_id, None)

    def group_broker(self, group_id: int) -> Broker:
        return self._brokers.get(group_id, Broker.QUOTEX)

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
        broker = self.group_broker(signal.group_id)
        if (refused := self._executor.refusal(broker, signal.asset, signal.duration_s)) is not None:
            self._ignore(signal, refused)
            return
        partner: Chain | None = None
        if settings.strategy in FLIP_STRATEGIES and (
            running := self.active_chains(signal.group_id)
        ):
            if (refusal := _pair_refusal(settings, signal, running)) is not None:
                self._ignore(signal, refusal)
                return
            partner = running[0]
        self._start_chain(signal, settings, broker, partner=partner)

    def open_session_chain(self, signal: Signal, *, run_id: UUID, pair_no: int) -> UUID | None:
        """Start one leg of a trading session's pair (decision D-71). The session scheduler is the
        gatekeeper, so decision D-9 is not applied. Returns the chain's id, or None if nothing was
        started (the kill switch, a paused group, no settings: the inbox row says why)."""
        if (blocked := self._guard.signal_block_reason(signal.group_id)) is not None:
            self._ignore(signal, blocked)
            return None
        settings = self._settings.get(signal.group_id)
        if settings is None:
            self._ignore(signal, "the session has no strategy settings")
            return None
        broker = self.group_broker(signal.group_id)
        if (refused := self._executor.refusal(broker, signal.asset, signal.duration_s)) is not None:
            self._ignore(signal, refused)
            return None
        chain = self._start_chain(signal, settings, broker, session=(run_id, pair_no))
        return None if chain is None else chain.id

    def _start_chain(
        self,
        signal: Signal,
        settings: GroupSettingsRecord,
        broker: Broker,
        *,
        partner: Chain | None = None,
        session: tuple[UUID, int] | None = None,
    ) -> Chain | None:
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
                session_run_id=session[0] if session else None,
                pair_no=session[1] if session else None,
                broker=broker,
            ),
            now,
        )
        try:
            plan = chain.plan()
        except ValueError as exc:
            self._ignore(signal, f"cannot plan the first trade: {exc}")
            return None
        self._register(chain)
        if partner is not None:
            self._partner[chain.id] = partner.id
        # Not published here: the chain row points at the signal's inbox row, which the pipeline
        # publishes only after handing the signal over (see `_publish_after_inbox_row`). If
        # anything else is about to be said about the chain first (the owner ends it in the same
        # moment), `_announce` publishes the start just before it, so events never arrive out of
        # order.
        started = ChainStarted(occurred_at=now, chain=chain.to_record())
        self._unannounced[chain.id] = started
        self._publish_after_inbox_row(started)
        stamps = Stamps(signal.t_msg_received_ns, signal.t_parsed_ns, decided_ns)
        self._drivers[chain.id] = self._tasks.spawn(
            self._drive(chain, plan, stamps), name=f"chain-{chain.id}"
        )
        return chain

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
        if isinstance(event, ChainStarted):
            asyncio.get_running_loop().call_soon(self._announce, event.chain.id)
        else:
            asyncio.get_running_loop().call_soon(self._bus.publish, event)

    def _announce(self, chain_id: UUID) -> None:
        """Publish the chain's `chain.started` if it has not gone out yet. Always called before
        any later event about the chain, so the database sees them in the order they happened:
        a `stopped` row must never be overwritten by an older `pending` one."""
        started = self._unannounced.pop(chain_id, None)
        if started is not None:
            self._bus.publish(started)

    # --- driving a chain ---

    async def _drive(self, chain: Chain, plan: StepPlan, stamps: Stamps) -> None:
        self._announce(chain.id)
        try:
            while chain.active:
                placed = await self._executor.place(chain, plan, stamps)
                if isinstance(placed, PlacedTrade):
                    self._note_order_sent(chain, placed)
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

    def _note_order_sent(self, chain: Chain, placed: PlacedTrade) -> None:
        """Log how far apart the two first orders of an opposite pair were sent. Orders go out one
        at a time (D-27), so the gap is at least the first order's confirmation round trip."""
        sent = placed.trade.t_order_sent_ns
        if chain.step != 0 or sent is None:
            return
        self._first_sent_ns[chain.id] = sent
        partner = self._partner.get(chain.id)
        other = self._first_sent_ns.get(partner) if partner is not None else None
        if other is not None:
            log.info(
                "opposite_pair_sent",
                group_id=chain.group_id,
                asset=chain.spec.asset,
                gap_ms=round(abs(sent - other) / 1_000_000, 1),
            )

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
        self._announce(chain.id)
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
        self._partner.pop(chain.id, None)
        self._first_sent_ns.pop(chain.id, None)

    # --- startup recovery ---

    def recover(self, state: RecoveryState) -> RecoverySummary:
        """Deal with what was in flight when the application stopped.

        We cannot see the broker's history, and a follow-up placed minutes late is not the trade the
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
        where: dict[int, Broker] = {}
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
            where[chain.group_id] = chain.broker
        for group_id, count in affected.items():
            self._bus.publish(
                RiskTripped(
                    occurred_at=now,
                    risk_event=RiskEventRecord(
                        id=new_id(),
                        occurred_at=now,
                        kind="restart_unknown",
                        message=f"{count} chain(s) were running when the application stopped "
                        f"and were marked unknown: check them on {where[group_id].label}",
                        group_id=group_id,
                    ),
                )
            )
        return RecoverySummary(sum(affected.values()), trades)
