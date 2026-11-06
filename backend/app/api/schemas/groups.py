"""Groups: what the owner sends to create or edit one, and what comes back."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.domain.enums import AssetSuffixMode, Strategy

# Bounds keep a typo from becoming a 10,000-step chain or a stake with a stray zero.
MAX_STEPS = 20
MAX_BASE_STAKE = Decimal("1000000")
MAX_MULTIPLIER = Decimal("1000")

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Multiplier = Annotated[Decimal, Field(gt=0, le=MAX_MULTIPLIER, max_digits=9, decimal_places=4)]


class GroupSettingsIn(BaseModel):
    """docs/DOMAIN.md section 5. There must be exactly one multiplier per step."""

    model_config = ConfigDict(extra="forbid")

    parser: str = Field(default="legacy_v1", min_length=1, max_length=50)
    asset_suffix_mode: AssetSuffixMode
    timezone: str = Field(
        min_length=1, max_length=64, description="`UTC-3`, `UTC+5:30` or an IANA zone name."
    )
    strategy: Strategy
    base_stake: Decimal = Field(gt=0, le=MAX_BASE_STAKE, max_digits=12, decimal_places=2)
    max_steps: int = Field(ge=0, le=MAX_STEPS)
    multipliers: list[Multiplier] = Field(default_factory=list, max_length=MAX_STEPS)
    min_payout_pct: int = Field(default=0, ge=0, le=100)
    allow_opposite_pair: bool = Field(
        default=False,
        description="Flip strategies only: while one chain runs, accept one more for the opposite "
        "direction on the same asset (two chains at most).",
    )

    @model_validator(mode="after")
    def _one_multiplier_per_step(self) -> Self:
        if len(self.multipliers) != self.max_steps:
            raise ValueError(
                "need exactly one multiplier per step: "
                f"max_steps={self.max_steps}, got {len(self.multipliers)}"
            )
        return self


class GroupCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telegram_chat_id: int = Field(description="Find it with `npm run telegram:dialogs`.")
    title: Title
    enabled: bool = True
    settings: GroupSettingsIn

    @field_validator("telegram_chat_id")
    @classmethod
    def _chat_id_is_not_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("telegram_chat_id cannot be 0")
        return value


class GroupUpdateIn(BaseModel):
    """Replaces the group's title, enabled flag and settings. The chat cannot be changed: that
    would be a different group."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    enabled: bool
    settings: GroupSettingsIn


class GroupSettingsOut(BaseModel):
    parser: str
    asset_suffix_mode: AssetSuffixMode
    timezone: str
    strategy: Strategy
    base_stake: Decimal
    max_steps: int
    multipliers: list[Decimal]
    min_payout_pct: int
    allow_opposite_pair: bool
    updated_at: datetime


class GroupOut(BaseModel):
    id: int
    telegram_chat_id: int
    title: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    settings: GroupSettingsOut | None
    paused: bool
    active_chains: int
