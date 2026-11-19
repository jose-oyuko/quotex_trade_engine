"""The Executor: sends one order and waits for its result. This is the hot path (ARCHITECTURE §4).

Between "the plan for this step exists" and "the order is sent" it does only in-memory work: it
builds a record, publishes an event (which never waits), and calls the adapter. There is no
database access, no balance lookup and no sleeping; the result is awaited as an event from the
adapter, with a timeout of `duration + margin` that ends in an `unknown` trade, never a guess.

Every trade is published twice before it settles: `pending` just before the order is sent (so a
crash between sending and confirmation leaves a trace that recovery turns into `unknown`), then
`open` once the broker confirmed it.

There is one adapter per broker that has a login (decision D-75); each trade goes to the adapter of
its chain's broker.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum

import structlog

from app.brokers.base import BrokerAdapter, ConnectionState, TradeOutcome, TradeResult
from app.brokers.errors import BrokerError, OrderAckTimeoutError, ResultTimeoutError
from app.core.clock import Clock
from app.domain.enums import AccountType, Broker, TradeStatus
from app.domain.ids import new_id
from app.domain.records import RiskEventRecord, TradeRecord
from app.engine.chain import Chain
from app.engine.risk import BlockKind, OrderRequest, RiskGuard
from app.engine.strategies import StepPlan
from app.events.bus import EventBus
from app.events.types import RiskTripped, TradeOpened, TradeSettled

log = structlog.get_logger()

RESULT_MARGIN_S = 60.0  # how long past the expiry we wait for a result before calling it unknown
REMEMBERED_RESULTS = 2_000  # settled trades kept in memory, in case the broker corrects one (D-82)


class StepKind(StrEnum):
    WON = "won"
    LOST = "lost"
    DRAW = "draw"
    FAILED = "failed"  # the order certainly did not reach the broker
    BLOCKED = "blocked"  # the risk guard refused it; nothing was sent
    UNKNOWN = "unknown"  # the order may exist, or its result is missing


@dataclass(slots=True, frozen=True)
class Stamps:
    """Monotonic readings carried from the signal into the trade (None for follow-ups)."""

    msg_received_ns: int | None
    parsed_ns: int | None
    decided_ns: int


@dataclass(slots=True, frozen=True)
class PlacedTrade:
    trade: TradeRecord  # status OPEN, with the broker's order id


@dataclass(slots=True, frozen=True)
class StepOutcome:
    kind: StepKind
    trade: TradeRecord  # the final record of this step's trade
    detail: str | None = None
    stop: bool = False  # BLOCKED by the kill switch: the chain is stopped, not failed


_OUTCOME_KIND = {
    TradeOutcome.WON: StepKind.WON,
    TradeOutcome.LOST: StepKind.LOST,
    TradeOutcome.DRAW: StepKind.DRAW,
}
_OUTCOME_STATUS = {
    TradeOutcome.WON: TradeStatus.WON,
    TradeOutcome.LOST: TradeStatus.LOST,
    TradeOutcome.DRAW: TradeStatus.DRAW,
}


class Executor:
    def __init__(
        self,
        adapters: Mapping[Broker, BrokerAdapter],
        *,
        guard: RiskGuard,
        clock: Clock,
        bus: EventBus,
        result_margin_s: float = RESULT_MARGIN_S,
        switched_off: set[Broker] | None = None,
    ) -> None:
        if not adapters:
            raise ValueError("the executor needs at least one broker")
        self._adapters = dict(adapters)
        self._off = switched_off if switched_off is not None else set()  # shared with the engine
        self._settled: OrderedDict[str, TradeRecord] = OrderedDict()  # by broker order id
        for adapter in self._adapters.values():
            adapter.set_correction_handler(self._corrected)
        self._guard = guard
        self._clock = clock
        self._bus = bus
        self._margin = result_margin_s

    @property
    def result_margin_s(self) -> float:
        """How long past a trade's expiry its result is waited for."""
        return self._margin

    @property
    def adapters(self) -> Mapping[Broker, BrokerAdapter]:
        return self._adapters

    def is_off(self, broker: Broker) -> bool:
        """The owner switched this broker off (decision D-81)."""
        return broker in self._off

    def adapter(self, broker: Broker) -> BrokerAdapter | None:
        """The broker's adapter, or None when it has no login (it was not built)."""
        return self._adapters.get(broker)

    @property
    def account_type(self) -> AccountType:
        """The account every broker is on: one demo/real switch for all (decision D-75)."""
        return next(iter(self._adapters.values())).account_type

    def refusal(self, broker: Broker, asset: str, duration_s: int) -> str | None:
        """Why a chain on `broker` for this asset and trade length must not start, from memory:
        the broker has no login, is not connected, or would surely refuse the order. None if it may
        start (the risk guard and the broker still decide on each order)."""
        adapter = self._adapters.get(broker)
        if adapter is None:
            return f"{broker.label} is not set up: its login is missing"
        if broker in self._off:
            return f"{broker.label} is switched off"
        if adapter.state is not ConnectionState.CONNECTED:
            return f"{broker.label} is not connected"
        return adapter.order_refusal(asset, duration_s)

    async def place(
        self, chain: Chain, plan: StepPlan, stamps: Stamps
    ) -> PlacedTrade | StepOutcome:
        """Send the order for `plan`. Returns the open trade, or the outcome if it was refused."""
        spec = chain.spec
        adapter = self._adapters.get(spec.broker)
        pending = TradeRecord(
            id=new_id(),
            chain_id=spec.id,
            group_id=spec.group_id,
            step=plan.step,
            asset=spec.asset,
            direction=plan.direction,
            duration_s=spec.duration_s,
            stake=plan.stake,
            account_type=spec.account_type,
            status=TradeStatus.PENDING,
            created_at=self._clock.now(),
            payout_pct=None if adapter is None else _payout(adapter, spec.asset, spec.duration_s),
            t_msg_received_ns=stamps.msg_received_ns,
            t_parsed_ns=stamps.parsed_ns,
            t_decided_ns=stamps.decided_ns,
            broker=spec.broker,
        )
        if adapter is None:
            return self._end(
                pending,
                StepKind.FAILED,
                f"{spec.broker.label} is not set up: its login is missing; order not sent",
            )
        if adapter.state is not ConnectionState.CONNECTED:
            # A step is sent when it is due or not at all (decision D-79): nothing waits for the
            # connection to come back.
            detail = (
                f"missed: step {plan.step} was due while {spec.broker.label} was not connected; "
                "it is never sent late"
                if plan.step > 0
                else f"{spec.broker.label} is not connected; order not sent"
            )
            return self._end(pending, StepKind.FAILED, detail)
        if adapter.account_type is not spec.account_type:
            return self._end(
                pending,
                StepKind.FAILED,
                f"the account changed from {spec.account_type.value} to "
                f"{adapter.account_type.value} after this chain started; order not sent",
            )
        decision = self._guard.admit(
            OrderRequest(
                trade_id=pending.id,
                chain_id=spec.id,
                group_id=spec.group_id,
                asset=spec.asset,
                step=plan.step,
                stake=plan.stake,
                account_type=spec.account_type,
                payout_pct=pending.payout_pct,
                min_payout_pct=spec.min_payout_pct,
                broker=spec.broker,
            )
        )
        if not decision.allowed:
            return self._end(
                pending,
                StepKind.BLOCKED,
                f"blocked by the risk guard ({decision.kind.value if decision.kind else '?'}): "
                f"{decision.message}",
                stop=decision.kind is BlockKind.KILL_SWITCH,
            )
        self._bus.publish(TradeOpened(occurred_at=pending.created_at, trade=pending))
        try:
            ack = await adapter.place_order(spec.asset, plan.direction, spec.duration_s, plan.stake)
        except OrderAckTimeoutError as exc:
            return self._end(pending, StepKind.UNKNOWN, f"order sent, no confirmation: {exc}")
        except BrokerError as exc:
            return self._end(pending, StepKind.FAILED, f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            # We cannot tell whether the order left the machine: never assume it did not.
            log.exception("place_order_crashed", chain_id=str(spec.id))
            return self._end(pending, StepKind.UNKNOWN, f"unexpected {type(exc).__name__}: {exc}")

        now = self._clock.now()
        opened = replace(
            pending,
            status=TradeStatus.OPEN,
            broker_order_id=ack.order_id,
            opened_at=now,
            expires_at=now + timedelta(seconds=spec.duration_s),
            t_order_sent_ns=ack.t_order_sent_ns,
            t_order_acked_ns=ack.t_order_acked_ns,
        )
        self._bus.publish(TradeOpened(occurred_at=now, trade=opened))
        return PlacedTrade(opened)

    async def settle(self, placed: PlacedTrade) -> StepOutcome:
        """Wait for the trade's result (as an event, never a fixed sleep)."""
        trade = placed.trade
        order_id = trade.broker_order_id or ""
        adapter = self._adapters.get(trade.broker)
        try:
            if adapter is None:  # pragma: no cover - a placed trade's broker always exists
                raise BrokerError(f"{trade.broker.label} is not set up")
            result = await adapter.await_result(order_id, trade.duration_s + self._margin)
        except ResultTimeoutError as exc:
            return self._end(trade, StepKind.UNKNOWN, f"no result in time: {exc}")
        except BrokerError as exc:
            return self._end(trade, StepKind.UNKNOWN, f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            log.exception("await_result_crashed", trade_id=str(trade.id))
            return self._end(trade, StepKind.UNKNOWN, f"unexpected {type(exc).__name__}: {exc}")

        now = self._clock.now()
        settled = replace(
            trade,
            status=_OUTCOME_STATUS[result.outcome],
            profit=result.profit,
            settled_at=now,
        )
        self._guard.settled(settled)  # frees the reservation and books the profit for the day
        self._bus.publish(TradeSettled(occurred_at=now, trade=settled))
        self._settled[order_id] = settled
        while len(self._settled) > REMEMBERED_RESULTS:
            self._settled.popitem(last=False)
        return StepOutcome(_OUTCOME_KIND[result.outcome], settled)

    def _corrected(self, result: TradeResult) -> None:
        """The broker's own result differs from the one it reported early (decision D-82): the
        trade is corrected and the day's figures with it, loudly. What the chain already did on
        the early result (a next step, or none) cannot be undone."""
        trade = self._settled.pop(result.order_id, None)
        if trade is None:
            log.error("result_correction_for_unknown_trade", order_id=result.order_id)
            return
        now = self._clock.now()
        corrected = replace(
            trade,
            status=_OUTCOME_STATUS[result.outcome],
            profit=result.profit,
            error=(
                f"corrected by {trade.broker.label}: reported early as {trade.status.value} "
                f"{trade.profit}, its own result is {result.outcome.value} {result.profit}"
            ),
        )
        self._guard.rebook(trade, corrected)
        self._bus.publish(TradeSettled(occurred_at=now, trade=corrected))
        self._bus.publish(
            RiskTripped(
                occurred_at=now,
                risk_event=RiskEventRecord(
                    id=new_id(),
                    occurred_at=now,
                    kind="early_result_corrected",
                    message=f"{trade.asset} step {trade.step}: {corrected.error}. The chain had "
                    "already acted on the early result.",
                    group_id=trade.group_id,
                ),
            )
        )

    # --- internals ---

    def _end(
        self, trade: TradeRecord, kind: StepKind, detail: str, *, stop: bool = False
    ) -> StepOutcome:
        refused = kind in (StepKind.FAILED, StepKind.BLOCKED)
        status = TradeStatus.FAILED if refused else TradeStatus.UNKNOWN
        now = self._clock.now()
        ended = replace(trade, status=status, error=detail, settled_at=now)
        self._guard.release(trade.id)  # not open any more, whatever happened to it
        self._bus.publish(TradeSettled(occurred_at=now, trade=ended))
        return StepOutcome(kind, ended, detail, stop)


def _payout(adapter: BrokerAdapter, asset: str, duration_s: int) -> int | None:
    try:
        return adapter.payout(asset, duration_s // 60)
    except BrokerError:
        return None  # a doubtful payout figure must not stop a trade the group asked for
