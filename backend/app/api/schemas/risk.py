"""Risk limits and the owner's controls."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import AccountType

Money = Annotated[Decimal, Field(gt=0, le=Decimal("100000000"), max_digits=14, decimal_places=2)]


class GroupRiskLimitsIn(BaseModel):
    """Limits of one group, on top of the global ones. Leave a field out (null) for no limit."""

    model_config = ConfigDict(extra="forbid")

    max_stake: Money | None = None
    daily_stop_loss: Money | None = None
    daily_profit_target: Money | None = None


class RiskLimitsIn(BaseModel):
    """The global limits. Null means no limit. Reaching `max_*` is allowed, exceeding it is not;
    reaching the daily stop-loss or profit target ends trading for the day (decision D-37)."""

    model_config = ConfigDict(extra="forbid")

    max_stake: Money | None = None
    max_concurrent_trades: int | None = Field(default=None, ge=1, le=1000)
    max_exposure: Money | None = None
    max_chain_trades: int | None = Field(default=None, ge=1, le=100)
    daily_stop_loss: Money | None = None
    daily_profit_target: Money | None = None
    reset_timezone: str = Field(default="UTC", min_length=1, max_length=64)
    reset_time: time = time(0, 0)

    @field_validator("reset_time")
    @classmethod
    def _whole_minutes(cls, value: time) -> time:
        if value.second or value.microsecond:
            raise ValueError("reset_time must be a whole minute, like 04:30")
        return value.replace(tzinfo=None)


class GroupRiskLimitsOut(BaseModel):
    max_stake: Decimal | None
    daily_stop_loss: Decimal | None
    daily_profit_target: Decimal | None


class RiskLimitsOut(BaseModel):
    max_stake: Decimal | None
    max_concurrent_trades: int | None
    max_exposure: Decimal | None
    max_chain_trades: int | None
    daily_stop_loss: Decimal | None
    daily_profit_target: Decimal | None
    reset_timezone: str
    reset_time: str = Field(description="HH:MM in `reset_timezone`.")


class ControlsOut(BaseModel):
    kill_switch: bool
    paused_groups: list[int]
    limits: RiskLimitsOut
    group_limits: dict[int, GroupRiskLimitsOut]


class DayOut(BaseModel):
    """The day the daily limits count, for the account in use."""

    account_type: AccountType
    since: datetime
    pnl: Decimal = Field(description="Net result since `since`; negative is a loss.")


class RiskOut(BaseModel):
    controls: ControlsOut
    day: DayOut | None = Field(description="Null while the engine is not running.")
    open_trades: int | None
    open_exposure: Decimal | None


class KillSwitchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop_chains: bool = Field(
        default=False,
        description="Also end the running chains now (their open trades still settle).",
    )


class AccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_type: AccountType


class AccountOut(BaseModel):
    account_type: AccountType
    real_trading_allowed: bool
