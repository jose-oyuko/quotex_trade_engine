"""Trading sessions: what the owner sends to set one up, and what comes back (decision D-71)."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.api.schemas.groups import MAX_BASE_STAKE, MAX_STEPS, Multiplier
from app.domain.enums import (
    AccountType,
    Broker,
    RepeatKind,
    RunEndReason,
    RunState,
    SessionMode,
    Strategy,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Money = Annotated[Decimal, Field(gt=0, le=MAX_BASE_STAKE, max_digits=12, decimal_places=2)]


class SessionStrategyIn(BaseModel):
    """The strategy part of a session: the same rules as a group's (docs/DOMAIN.md section 5). The
    CALL and the PUT of every pair are two chains that each follow it."""

    model_config = ConfigDict(extra="forbid")

    strategy: Strategy
    base_stake: Decimal = Field(gt=0, le=MAX_BASE_STAKE, max_digits=12, decimal_places=2)
    max_steps: int = Field(ge=0, le=MAX_STEPS)
    multipliers: list[Multiplier] = Field(default_factory=list, max_length=MAX_STEPS)
    min_payout_pct: int = Field(
        default=0,
        ge=0,
        le=100,
        description="A round is skipped, and nothing is sent, if the asset pays less than this.",
    )

    @model_validator(mode="after")
    def _one_multiplier_per_step(self) -> Self:
        if len(self.multipliers) != self.max_steps:
            raise ValueError(
                "need exactly one multiplier per step: "
                f"max_steps={self.max_steps}, got {len(self.multipliers)}"
            )
        return self


class SessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    enabled: bool = True
    broker: Broker = Field(
        default=Broker.QUOTEX,
        description="Where its trades are placed: `quotex` or `deriv` (decision D-75).",
    )
    asset: str = Field(
        min_length=3,
        max_length=20,
        description="Quotex: `EURUSD` or `EURUSD_otc`. Deriv: a forex pair (`EURUSD`, 15 minutes "
        "or more) or a synthetic index (`R_75`, `1HZ100V`, 1 minute or more).",
    )
    duration_s: int = Field(
        description="The trade length in seconds, also the candle length: 60, 120, 180, 300, 600, "
        "900, 1800, 3600 or 14400."
    )
    start_time: time = Field(description="Wall-clock time in `timezone`, `HH:MM`.")
    end_time: time = Field(
        description="Wall-clock time in `timezone`. Before `start_time` means the window crosses "
        "midnight."
    )
    timezone: str = Field(
        min_length=1, max_length=64, description="`UTC-3`, `UTC+5:30` or an IANA zone name."
    )
    repeat: RepeatKind = Field(
        description="`once`: the next window only, never again. `weekdays`: on the chosen days."
    )
    weekdays: list[int] = Field(
        default_factory=list,
        max_length=7,
        description="0 = Monday ... 6 = Sunday. Needed when `repeat` is `weekdays`.",
    )
    pause_s: int = Field(
        default=0,
        ge=0,
        le=86_400,
        description="Seconds to wait after both chains of a pair have ended, before the next pair.",
    )
    profit_target: Money | None = Field(
        default=None, description="The session stops opening pairs when its profit reaches this."
    )
    loss_limit: Money | None = Field(
        default=None,
        description="The session stops opening pairs when its loss reaches this. Chains already "
        "running finish, so this does not cap the total loss.",
    )
    max_pairs: int | None = Field(default=None, ge=1, le=100_000)
    mode: SessionMode = Field(
        default=SessionMode.SEQUENTIAL,
        description="`sequential`: one pair at a time, the next after both chains ended (and "
        "`pause_s`). `every_candle`: a pair at every candle, up to `max_open_pairs` open at once.",
    )
    max_open_pairs: int = Field(
        default=1,
        ge=1,
        le=50,
        description="`every_candle` only: at most this many pairs open at once (a pair is open "
        "while one of its chains runs); a candle that finds the limit reached is skipped.",
    )
    strategy: SessionStrategyIn

    @model_validator(mode="after")
    def _weekdays_are_days(self) -> Self:
        if any(not 0 <= d <= 6 for d in self.weekdays):
            raise ValueError("weekdays are numbers from 0 (Monday) to 6 (Sunday)")
        if self.repeat is RepeatKind.WEEKDAYS and not self.weekdays:
            raise ValueError("choose at least one day of the week")
        return self


class SessionStrategyOut(BaseModel):
    strategy: Strategy
    base_stake: Decimal
    max_steps: int
    multipliers: list[Decimal]
    min_payout_pct: int


class SessionRunOut(BaseModel):
    id: UUID
    session_id: int
    started_by: str = Field(description="`schedule` or `manual`.")
    account_type: AccountType
    started_at: datetime
    window_end: datetime
    state: RunState
    updated_at: datetime
    pairs_opened: int
    rounds_skipped: int
    lopsided_pairs: int = Field(description="Pairs where only one leg was ever running.")
    profit: Decimal
    ended_at: datetime | None
    end_reason: RunEndReason | None
    note: str | None


class SessionOut(BaseModel):
    id: int
    name: str
    enabled: bool
    group_id: int = Field(description="The session's hidden group: its chains and trades carry it.")
    broker: Broker
    asset: str
    duration_s: int
    start_time: time
    end_time: time
    timezone: str
    repeat: RepeatKind
    weekdays: list[int]
    pause_s: int
    profit_target: Decimal | None
    loss_limit: Decimal | None
    max_pairs: int | None
    mode: SessionMode
    max_open_pairs: int
    strategy: SessionStrategyOut | None
    next_window_start: datetime | None = Field(
        description="When it will start by itself next (null: switched off, or a finished 'once')."
    )
    next_window_end: datetime | None
    warnings: list[str]
    active_run: SessionRunOut | None
    created_at: datetime
    updated_at: datetime
