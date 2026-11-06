"""Plain, immutable value objects for everything the database stores.

The engine, the event bus and the repositories speak in these records; only `app/db` knows about
SQLAlchemy. Field names match the table columns one-to-one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.domain.enums import (
    AccountType,
    AssetSuffixMode,
    ChainStatus,
    Direction,
    SignalStatus,
    Strategy,
    TradeStatus,
)

type JsonScalar = str | int | float | bool | None


@dataclass(slots=True, frozen=True)
class GroupRecord:
    """A Telegram group/channel being listened to. `id` is None until the database assigns it."""

    telegram_chat_id: int
    title: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    id: int | None = None


@dataclass(slots=True, frozen=True)
class GroupSettingsRecord:
    """Per-group strategy settings (docs/DOMAIN.md section 5)."""

    group_id: int
    parser: str
    asset_suffix_mode: AssetSuffixMode
    timezone: str
    strategy: Strategy
    base_stake: Decimal
    max_steps: int
    multipliers: tuple[Decimal, ...]
    min_payout_pct: int
    updated_at: datetime
    # Flip strategies only: while one chain runs, accept one more, for the opposite direction on
    # the same asset (at most two chains). Off = one chain at a time (decision D-9, D-70).
    allow_opposite_pair: bool = False

    def __post_init__(self) -> None:
        if self.base_stake <= 0:
            raise ValueError("base_stake must be greater than 0")
        if self.max_steps < 0:
            raise ValueError("max_steps must be 0 or more")
        if len(self.multipliers) != self.max_steps:
            raise ValueError(
                f"need exactly one multiplier per step: max_steps={self.max_steps}, "
                f"got {len(self.multipliers)}"
            )
        if any(m <= 0 for m in self.multipliers):
            raise ValueError("every multiplier must be greater than 0")
        if not 0 <= self.min_payout_pct <= 100:
            raise ValueError("min_payout_pct must be between 0 and 100")


@dataclass(slots=True, frozen=True)
class SignalRecord:
    """One received Telegram message and what the pipeline made of it (the signal inbox)."""

    id: UUID
    group_id: int
    telegram_message_id: int | None
    received_at: datetime
    raw_text: str
    status: SignalStatus
    reason: str | None = None
    asset: str | None = None
    direction: Direction | None = None
    duration_s: int | None = None
    entry_time: datetime | None = None


@dataclass(slots=True, frozen=True)
class ChainRecord:
    """A chain: the original signal trade plus its follow-ups. Settings are snapshotted so that
    editing a group mid-chain does not change a chain that is already running."""

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
    multipliers: tuple[Decimal, ...]
    created_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None


@dataclass(slots=True, frozen=True)
class TradeRecord:
    """One order. The `t_*_ns` fields are monotonic clock readings (docs/ARCHITECTURE.md section 4):
    only differences between them within one process run mean anything."""

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
    payout_pct: int | None = None
    profit: Decimal | None = None
    broker_order_id: str | None = None
    opened_at: datetime | None = None
    expires_at: datetime | None = None
    settled_at: datetime | None = None
    error: str | None = None
    t_msg_received_ns: int | None = None
    t_parsed_ns: int | None = None
    t_decided_ns: int | None = None
    t_order_sent_ns: int | None = None
    t_order_acked_ns: int | None = None


@dataclass(slots=True, frozen=True)
class RiskEventRecord:
    id: UUID
    occurred_at: datetime
    kind: str
    message: str
    group_id: int | None = None
    details: Mapping[str, JsonScalar] | None = None


@dataclass(slots=True, frozen=True)
class BalanceSnapshotRecord:
    id: UUID
    taken_at: datetime
    account_type: AccountType
    balance: Decimal


@dataclass(slots=True, frozen=True)
class AppSettingRecord:
    key: str
    value: JsonScalar
    updated_at: datetime
