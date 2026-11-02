"""Typed events. Each carries a snapshot of the record it describes, so a consumer (the DB writer,
the WebSocket hub) never has to ask anyone for more data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from app.domain.records import (
    BalanceSnapshotRecord,
    ChainRecord,
    RiskEventRecord,
    SignalRecord,
    TradeRecord,
)


@dataclass(slots=True, frozen=True, kw_only=True)
class Event:
    name: ClassVar[str]
    occurred_at: datetime


@dataclass(slots=True, frozen=True, kw_only=True)
class SignalReceived(Event):
    name: ClassVar[str] = "signal.received"
    signal: SignalRecord


@dataclass(slots=True, frozen=True, kw_only=True)
class ChainStarted(Event):
    name: ClassVar[str] = "chain.started"
    chain: ChainRecord


@dataclass(slots=True, frozen=True, kw_only=True)
class ChainAdvanced(Event):
    name: ClassVar[str] = "chain.advanced"
    chain: ChainRecord


@dataclass(slots=True, frozen=True, kw_only=True)
class ChainEnded(Event):
    name: ClassVar[str] = "chain.ended"
    chain: ChainRecord


@dataclass(slots=True, frozen=True, kw_only=True)
class TradeOpened(Event):
    name: ClassVar[str] = "trade.opened"
    trade: TradeRecord


@dataclass(slots=True, frozen=True, kw_only=True)
class TradeSettled(Event):
    name: ClassVar[str] = "trade.settled"
    trade: TradeRecord


@dataclass(slots=True, frozen=True, kw_only=True)
class RiskTripped(Event):
    name: ClassVar[str] = "risk.tripped"
    risk_event: RiskEventRecord


@dataclass(slots=True, frozen=True, kw_only=True)
class BalanceUpdated(Event):
    name: ClassVar[str] = "balance.updated"
    snapshot: BalanceSnapshotRecord


@dataclass(slots=True, frozen=True, kw_only=True)
class ConnectionChanged(Event):
    """Telegram/Quotex connectivity. Shown live; not stored."""

    name: ClassVar[str] = "connection.changed"
    component: str
    connected: bool
    detail: str | None = None


# Events that end up as database rows.
PERSISTED_EVENTS: tuple[type[Event], ...] = (
    SignalReceived,
    ChainStarted,
    ChainAdvanced,
    ChainEnded,
    TradeOpened,
    TradeSettled,
    RiskTripped,
    BalanceUpdated,
)
