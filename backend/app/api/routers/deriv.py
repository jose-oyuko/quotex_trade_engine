"""Deriv on the dashboard (Phase 21): checking a stored token, and Deriv's list of assets."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DerivDep
from app.api.schemas.deriv import (
    DerivAccountOut,
    DerivAssetOut,
    DerivAssetsOut,
    DerivCheckIn,
    LengthOut,
)

router = APIRouter(prefix="/deriv", tags=["deriv"])


@router.post("/check", response_model=DerivAccountOut)
async def check(body: DerivCheckIn, deriv: DerivDep) -> DerivAccountOut:
    """Which Deriv account the stored demo (or real) token opens. Reads Deriv's account list
    only: nothing is traded, and the engine does not need to be stopped."""
    account = await deriv.check(body.account_type)
    return DerivAccountOut(
        account_id=account.account_id,
        account_type=account.account_type,
        currency=account.currency,
        balance=account.balance,
    )


@router.get("/assets", response_model=DerivAssetsOut)
async def assets(deriv: DerivDep) -> DerivAssetsOut:
    """Every asset Deriv lists, with the Rise/Fall trade lengths it allows, as the running engine
    knows them. Empty, with the reason, while the engine is not connected to Deriv."""
    found = deriv.assets()
    return DerivAssetsOut(
        available=found.available,
        reason=found.reason,
        items=[
            DerivAssetOut(
                asset=a.asset,
                name=a.name,
                market=a.market,
                is_open=a.is_open,
                lengths=None
                if a.lengths is None
                else [LengthOut(min_s=lo, max_s=hi) for lo, hi in a.lengths],
            )
            for a in found.assets
        ],
    )
