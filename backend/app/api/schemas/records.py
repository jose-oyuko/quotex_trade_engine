"""Response shapes for the things the database stores: signals, chains, trades, risk events.

Money is always a string in JSON (pydantic writes `Decimal` as text), never a float: the dashboard
must not do arithmetic on stakes with floating point.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.enums import (
    AccountType,
    ChainStatus,
    Direction,
    SignalStatus,
    Strategy,
    TradeStatus,
)
from app.domain.records import (
    BalanceSnapshotRecord,
    ChainRecord,
    RiskEventRecord,
    SignalRecord,
    TradeRecord,
)


class SignalOut(BaseModel):
    """`raw_text` is untrusted Telegram text: show it as plain text, never as HTML."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    group_id: int
    telegram_message_id: int | None
    received_at: datetime
    raw_text: str
    status: SignalStatus
    reason: str | None
    asset: str | None
    direction: Direction | None
    duration_s: int | None
    entry_time: datetime | None


class ChainOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    group_id: int
    signal_id: UUID | None
    asset: str
    origin_direction: Direction
    duration_s: int
    account_type: AccountType
    strategy: Strategy
    status: ChainStatus
    step: int
    consecutive_losses: int
    max_steps: int
    base_stake: Decimal
    multipliers: list[Decimal]
    created_at: datetime
    updated_at: datetime
    ended_at: datetime | None
    end_reason: str | None


class TradeLatency(BaseModel):
    """Milliseconds between the steps of the hot path (docs/ARCHITECTURE.md section 4). A field is
    null when the trade does not have both of its stamps (follow-ups have no Telegram message)."""

    signal_to_order_ms: float | None
    decision_to_order_ms: float | None
    order_ack_ms: float | None


class TradeOut(BaseModel):
    id: UUID
    chain_id: UUID
    group_id: int
    step: int
    asset: str
    direction: Direction
    duration_s: int
    stake: Decimal
    account_type: AccountType
    status: TradeStatus
    created_at: datetime
    payout_pct: int | None
    profit: Decimal | None
    broker_order_id: str | None
    opened_at: datetime | None
    expires_at: datetime | None
    settled_at: datetime | None
    error: str | None
    latency: TradeLatency


class RiskEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    kind: str
    message: str
    group_id: int | None
    details: dict[str, Any] | None


class BalanceOut(BaseModel):
    taken_at: datetime
    account_type: AccountType
    balance: Decimal


class ChainDetailOut(BaseModel):
    chain: ChainOut
    trades: list[TradeOut]
    signal: SignalOut | None


def _ms(start: int | None, end: int | None) -> float | None:
    return None if start is None or end is None else (end - start) / 1_000_000


def trade_out(trade: TradeRecord) -> TradeOut:
    return TradeOut(
        id=trade.id,
        chain_id=trade.chain_id,
        group_id=trade.group_id,
        step=trade.step,
        asset=trade.asset,
        direction=trade.direction,
        duration_s=trade.duration_s,
        stake=trade.stake,
        account_type=trade.account_type,
        status=trade.status,
        created_at=trade.created_at,
        payout_pct=trade.payout_pct,
        profit=trade.profit,
        broker_order_id=trade.broker_order_id,
        opened_at=trade.opened_at,
        expires_at=trade.expires_at,
        settled_at=trade.settled_at,
        error=trade.error,
        latency=TradeLatency(
            signal_to_order_ms=_ms(trade.t_msg_received_ns, trade.t_order_sent_ns),
            decision_to_order_ms=_ms(trade.t_decided_ns, trade.t_order_sent_ns),
            order_ack_ms=_ms(trade.t_order_sent_ns, trade.t_order_acked_ns),
        ),
    )


def chain_out(chain: ChainRecord) -> ChainOut:
    return ChainOut.model_validate(chain)


def signal_out(signal: SignalRecord) -> SignalOut:
    return SignalOut.model_validate(signal)


def risk_event_out(event: RiskEventRecord) -> RiskEventOut:
    return RiskEventOut.model_validate(event)


def balance_out(snapshot: BalanceSnapshotRecord) -> BalanceOut:
    return BalanceOut(
        taken_at=snapshot.taken_at, account_type=snapshot.account_type, balance=snapshot.balance
    )
