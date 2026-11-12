"""Plain, immutable value objects for everything the database stores.

The engine, the event bus and the repositories speak in these records; only `app/db` knows about
SQLAlchemy. Field names match the table columns one-to-one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from uuid import UUID

from app.domain.enums import (
    AccountType,
    AssetSuffixMode,
    ChainStatus,
    Direction,
    GroupSource,
    RepeatKind,
    RunEndReason,
    RunState,
    SessionMode,
    SignalStatus,
    Strategy,
    TradeStatus,
)

type JsonScalar = str | int | float | bool | None


@dataclass(slots=True, frozen=True)
class GroupRecord:
    """A Telegram group/channel being listened to, or the hidden group of a trading session (which
    has no chat). `id` is None until the database assigns it."""

    telegram_chat_id: int | None
    title: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    id: int | None = None
    source: GroupSource = GroupSource.TELEGRAM


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
    # Chains opened by a trading session: the run, and which pair of the run (1, 2, ...)
    session_run_id: UUID | None = None
    pair_no: int | None = None


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


@dataclass(slots=True, frozen=True)
class SessionRecord:
    """A trading session as the owner saved it (decision D-71): one asset, a time window that
    repeats (or not), and when to stop. The strategy part (stakes, steps, minimum payout) lives in
    the group settings of its hidden group, `group_id`."""

    name: str
    enabled: bool
    group_id: int
    asset: str  # the Quotex name: "EURUSD" or "EURUSD_otc"
    duration_s: int  # the trade length, which is also the candle length
    start_time: time  # wall-clock times in `timezone`; `end_time` may be before `start_time`
    end_time: time  # (the window then crosses midnight)
    timezone: str
    repeat: RepeatKind
    weekdays: tuple[int, ...]  # 0 = Monday ... 6 = Sunday; used when `repeat` is WEEKDAYS
    pause_s: int  # sequential mode: wait this long after a pair is over before the next
    created_at: datetime
    updated_at: datetime
    # ONCE: the window is the first one that starts at or after this moment
    once_after: datetime
    profit_target: Decimal | None = None
    loss_limit: Decimal | None = None
    max_pairs: int | None = None
    id: int | None = None
    # How pairs are spaced (D-73): one at a time, or one at every candle with at most
    # `max_open_pairs` open at once (a pair is open while at least one of its chains runs)
    mode: SessionMode = SessionMode.SEQUENTIAL
    max_open_pairs: int = 1

    def __post_init__(self) -> None:
        if self.max_open_pairs < 1:
            raise ValueError("the number of open pairs must be at least 1")
        if not self.name.strip():
            raise ValueError("the session needs a name")
        if self.duration_s <= 0:
            raise ValueError("the trade length must be greater than 0")
        if self.start_time == self.end_time:
            raise ValueError("the start and the end of the window must differ")
        if self.pause_s < 0:
            raise ValueError("the pause between pairs cannot be negative")
        if self.profit_target is not None and self.profit_target <= 0:
            raise ValueError("the profit target must be greater than 0 (or unset)")
        if self.loss_limit is not None and self.loss_limit <= 0:
            raise ValueError("the loss limit must be greater than 0 (or unset)")
        if self.max_pairs is not None and self.max_pairs < 1:
            raise ValueError("the maximum number of pairs must be at least 1 (or unset)")
        if self.repeat is RepeatKind.WEEKDAYS and not self.weekdays:
            raise ValueError("choose at least one day of the week")
        if any(not 0 <= d <= 6 for d in self.weekdays) or len(set(self.weekdays)) != len(
            self.weekdays
        ):
            raise ValueError("weekdays must be distinct numbers from 0 (Monday) to 6 (Sunday)")


@dataclass(slots=True, frozen=True)
class SessionRunRecord:
    """One occurrence of a session (one window), with what it did and why it ended."""

    id: UUID
    session_id: int
    started_by: str  # "schedule" or "manual"
    account_type: AccountType
    started_at: datetime
    window_end: datetime
    state: RunState
    updated_at: datetime
    pairs_opened: int = 0
    rounds_skipped: int = 0
    lopsided_pairs: int = 0  # a pair whose second leg was refused after the first was sent
    profit: Decimal = Decimal(0)
    ended_at: datetime | None = None
    end_reason: RunEndReason | None = None
    note: str | None = None  # the last thing worth saying (a skipped round's reason, an error)
