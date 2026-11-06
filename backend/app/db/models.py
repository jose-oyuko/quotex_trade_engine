"""SQLAlchemy table definitions.

Portable on purpose (decision D-3): plain types, enums stored as short strings, no SQLite-only
constructs. The only dialect-minded detail is the integer primary key of `groups`, a plain
`Integer` so that SQLite auto-increments it (PostgreSQL does too).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import DecimalList, Money, UTCDateTime
from app.domain.enums import (
    AccountType,
    AssetSuffixMode,
    ChainStatus,
    Direction,
    SignalStatus,
    Strategy,
    TradeStatus,
    UserRole,
)


def _enum[E: StrEnum](enum_class: type[E]) -> Enum:
    """Store the enum's value in a VARCHAR; no database-native enum, no CHECK on the values."""
    return Enum(
        enum_class,
        native_enum=False,
        create_constraint=False,
        length=24,
        values_callable=lambda members: [m.value for m in members],
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    title: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class GroupSettings(Base):
    __tablename__ = "group_settings"
    __table_args__ = (
        CheckConstraint("base_stake > 0", name="base_stake_positive"),
        CheckConstraint("max_steps >= 0", name="max_steps_not_negative"),
        CheckConstraint("min_payout_pct BETWEEN 0 AND 100", name="min_payout_range"),
    )

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    parser: Mapped[str] = mapped_column(String(64))
    asset_suffix_mode: Mapped[AssetSuffixMode] = mapped_column(_enum(AssetSuffixMode))
    timezone: Mapped[str] = mapped_column(String(64))
    strategy: Mapped[Strategy] = mapped_column(_enum(Strategy))
    base_stake: Mapped[Decimal] = mapped_column(Money)
    max_steps: Mapped[int] = mapped_column(SmallInteger)
    multipliers: Mapped[tuple[Decimal, ...]] = mapped_column(DecimalList)
    min_payout_pct: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    allow_opposite_pair: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )


class Signal(Base):
    """The signal inbox: one row per received message, parsed or not."""

    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_group_id_received_at", "group_id", "received_at"),
        Index("ix_signals_group_id_telegram_message_id", "group_id", "telegram_message_id"),
        Index("ix_signals_status_received_at", "status", "received_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[SignalStatus] = mapped_column(_enum(SignalStatus))
    reason: Mapped[str | None] = mapped_column(String(255))
    asset: Mapped[str | None] = mapped_column(String(32))
    direction: Mapped[Direction | None] = mapped_column(_enum(Direction))
    duration_s: Mapped[int | None] = mapped_column(Integer)
    entry_time: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Chain(Base):
    __tablename__ = "chains"
    __table_args__ = (
        Index("ix_chains_status", "status"),
        Index("ix_chains_group_id_asset_status", "group_id", "asset", "status"),
        Index("ix_chains_account_type_created_at", "account_type", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    signal_id: Mapped[UUID | None] = mapped_column(ForeignKey("signals.id"))
    asset: Mapped[str] = mapped_column(String(32))
    origin_direction: Mapped[Direction] = mapped_column(_enum(Direction))
    duration_s: Mapped[int] = mapped_column(Integer)
    account_type: Mapped[AccountType] = mapped_column(_enum(AccountType))
    strategy: Mapped[Strategy] = mapped_column(_enum(Strategy))
    status: Mapped[ChainStatus] = mapped_column(_enum(ChainStatus))
    step: Mapped[int] = mapped_column(SmallInteger)
    consecutive_losses: Mapped[int] = mapped_column(SmallInteger)
    max_steps: Mapped[int] = mapped_column(SmallInteger)
    base_stake: Mapped[Decimal] = mapped_column(Money)
    multipliers: Mapped[tuple[Decimal, ...]] = mapped_column(DecimalList)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    end_reason: Mapped[str | None] = mapped_column(String(255))


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_chain_id_step", "chain_id", "step"),
        Index("ix_trades_status", "status"),
        Index("ix_trades_account_type_settled_at", "account_type", "settled_at"),
        Index(
            "ix_trades_group_id_account_type_settled_at", "group_id", "account_type", "settled_at"
        ),
        Index("ix_trades_account_type_asset", "account_type", "asset"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    chain_id: Mapped[UUID] = mapped_column(ForeignKey("chains.id"))
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    step: Mapped[int] = mapped_column(SmallInteger)
    asset: Mapped[str] = mapped_column(String(32))
    direction: Mapped[Direction] = mapped_column(_enum(Direction))
    duration_s: Mapped[int] = mapped_column(Integer)
    stake: Mapped[Decimal] = mapped_column(Money)
    account_type: Mapped[AccountType] = mapped_column(_enum(AccountType))
    status: Mapped[TradeStatus] = mapped_column(_enum(TradeStatus))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    payout_pct: Mapped[int | None] = mapped_column(SmallInteger)
    profit: Mapped[Decimal | None] = mapped_column(Money)
    broker_order_id: Mapped[str | None] = mapped_column(String(64))
    opened_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error: Mapped[str | None] = mapped_column(String(500))
    # Latency checkpoints: monotonic nanoseconds (see TradeRecord).
    t_msg_received_ns: Mapped[int | None] = mapped_column(BigInteger)
    t_parsed_ns: Mapped[int | None] = mapped_column(BigInteger)
    t_decided_ns: Mapped[int | None] = mapped_column(BigInteger)
    t_order_sent_ns: Mapped[int | None] = mapped_column(BigInteger)
    t_order_acked_ns: Mapped[int | None] = mapped_column(BigInteger)


class RiskEvent(Base):
    __tablename__ = "risk_events"
    __table_args__ = (Index("ix_risk_events_occurred_at", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    kind: Mapped[str] = mapped_column(String(64))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"))
    message: Mapped[str] = mapped_column(String(500))
    details: Mapped[dict[str, object] | None] = mapped_column(JSON)


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"
    __table_args__ = (
        Index("ix_balance_snapshots_account_type_taken_at", "account_type", "taken_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    taken_at: Mapped[datetime] = mapped_column(UTCDateTime)
    account_type: Mapped[AccountType] = mapped_column(_enum(AccountType))
    balance: Mapped[Decimal] = mapped_column(Money)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class User(Base):
    """A person who can log in. One admin for now (decision D-59)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AuthSession(Base):
    """A logged-in browser. Only the SHA-256 of the cookie's token is stored (decision D-60)."""

    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_id", "user_id"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class StoredSecret(Base):
    """A secret typed into the dashboard, encrypted (decision D-61). Never holds a plain value."""

    __tablename__ = "secrets"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
