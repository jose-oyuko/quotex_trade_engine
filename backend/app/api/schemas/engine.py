"""Bodies of the engine endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginItemOut(BaseModel):
    label: str
    present: bool
    source: Literal["dashboard", ".env", ".session file", "missing", "unreadable"]
    required: bool = Field(description="The engine cannot start without it.")


class BrokerNeedOut(BaseModel):
    broker: Literal["Deriv", "Quotex"]
    missing: list[str]


class EngineOut(BaseModel):
    state: Literal["stopped", "starting", "running", "stopping", "failed"]
    desired: bool = Field(description="It is started again when the application starts.")
    error: str | None = Field(description="Why the last start failed, in words.")
    since: datetime | None
    real_trading_allowed: bool
    logins: list[LoginItemOut] = Field(description="The logins it would use, never their values.")
    missing_logins: list[str] = Field(
        description="Every required login not there yet (the engine cannot start while any is)."
    )
    start_needs: list[BrokerNeedOut] = Field(
        description="Empty when a broker is ready. Otherwise each broker with the pieces it "
        "still lacks, the closest first: those of any ONE broker are enough (decision D-75)."
    )


class RealTradingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    password: str = Field(min_length=1, max_length=256, description="The owner's own password.")
