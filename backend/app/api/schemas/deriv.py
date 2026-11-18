"""Bodies of the Deriv endpoints (Phase 21). No answer carries a token or the app id."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import AccountType


class DerivCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_type: AccountType = Field(
        default=AccountType.DEMO, description="Which stored token to check: demo or real."
    )


class DerivAccountOut(BaseModel):
    account_id: str = Field(description="Deriv's account number, like VRTC1234 or CR5678.")
    account_type: AccountType
    currency: str | None
    balance: Decimal | None = Field(description="When Deriv's account list gives it.")


class LengthOut(BaseModel):
    min_s: int
    max_s: int


class DerivAssetOut(BaseModel):
    asset: str = Field(description="The name to use in a session: EURUSD, R_75.")
    name: str = Field(description="Deriv's own name: EUR/USD, Volatility 75 Index.")
    market: str = Field(description="forex, synthetic_index, ...")
    is_open: bool
    lengths: list[LengthOut] | None = Field(
        description="The Rise/Fall trade lengths it allows; null while they are not known yet."
    )


class DerivAssetsOut(BaseModel):
    available: bool
    reason: str | None = Field(description="Why there is no list, in words.")
    items: list[DerivAssetOut]
