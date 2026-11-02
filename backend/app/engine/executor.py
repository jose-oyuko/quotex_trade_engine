"""The Executor: sends one order and waits for its result. This is the hot path (ARCHITECTURE §4).

Between "the plan for this step exists" and "the order is sent" it does only in-memory work: it
builds a record, publishes an event (which never waits), and calls the adapter. There is no
database access, no balance lookup and no sleeping; the result is awaited as an event from the
adapter, with a timeout of `duration + margin` that ends in an `unknown` trade, never a guess.

Every trade is published twice before it settles: `pending` just before the order is sent (so a
crash between sending and confirmation leaves a trace that recovery turns into `unknown`), then
`open` once Quotex confirmed it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum

import structlog

from app.core.clock import Clock
from app.domain.enums import AccountType, TradeStatus
from app.domain.ids import new_id
from app.domain.records import TradeRecord
from app.engine.chain import Chain
from app.engine.strategies import StepPlan
from app.events.bus import EventBus
from app.events.types import TradeOpened, TradeSettled
from app.quotex.base import QuotexAdapter, TradeOutcome
from app.quotex.errors import OrderAckTimeoutError, QuotexError, ResultTimeoutError

log = structlog.get_logger()

RESULT_MARGIN_S = 60.0  # how long past the expiry we wait for a result before calling it unknown


class StepKind(StrEnum):
    WON = "won"
    LOST = "lost"
    DRAW = "draw"
    FAILED = "failed"  # the order certainly did not reach Quotex
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
        adapter: QuotexAdapter,
        *,
        clock: Clock,
        bus: EventBus,
        result_margin_s: float = RESULT_MARGIN_S,
    ) -> None:
        self._adapter = adapter
        self._clock = clock
        self._bus = bus
        self._margin = result_margin_s

    @property
    def account_type(self) -> AccountType:
        return self._adapter.account_type

    async def place(
        self, chain: Chain, plan: StepPlan, stamps: Stamps
    ) -> PlacedTrade | StepOutcome:
        """Send the order for `plan`. Returns the open trade, or the outcome if it was refused."""
        spec = chain.spec
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
            payout_pct=self._payout(spec.asset, spec.duration_s),
            t_msg_received_ns=stamps.msg_received_ns,
            t_parsed_ns=stamps.parsed_ns,
            t_decided_ns=stamps.decided_ns,
        )
        if self._adapter.account_type is not spec.account_type:
            return self._end(
                pending,
                StepKind.FAILED,
                f"the account changed from {spec.account_type.value} to "
                f"{self._adapter.account_type.value} after this chain started; order not sent",
            )
        self._bus.publish(TradeOpened(occurred_at=pending.created_at, trade=pending))
        try:
            ack = await self._adapter.place_order(
                spec.asset, plan.direction, spec.duration_s, plan.stake
            )
        except OrderAckTimeoutError as exc:
            return self._end(pending, StepKind.UNKNOWN, f"order sent, no confirmation: {exc}")
        except QuotexError as exc:
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
        try:
            result = await self._adapter.await_result(order_id, trade.duration_s + self._margin)
        except ResultTimeoutError as exc:
            return self._end(trade, StepKind.UNKNOWN, f"no result in time: {exc}")
        except QuotexError as exc:
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
        self._bus.publish(TradeSettled(occurred_at=now, trade=settled))
        return StepOutcome(_OUTCOME_KIND[result.outcome], settled)

    # --- internals ---

    def _payout(self, asset: str, duration_s: int) -> int | None:
        try:
            return self._adapter.payout(asset, duration_s // 60)
        except QuotexError:
            return None  # a doubtful payout figure must not stop a trade the group asked for

    def _end(self, trade: TradeRecord, kind: StepKind, detail: str) -> StepOutcome:
        status = TradeStatus.FAILED if kind is StepKind.FAILED else TradeStatus.UNKNOWN
        now = self._clock.now()
        ended = replace(trade, status=status, error=detail, settled_at=now)
        self._bus.publish(TradeSettled(occurred_at=now, trade=ended))
        return StepOutcome(kind, ended, detail)
