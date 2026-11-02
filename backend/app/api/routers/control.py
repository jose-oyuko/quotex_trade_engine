"""Risk limits, the kill switch, the account in use, status and the reports placeholder."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body

from app.api.deps import (
    EngineDep,
    LiveDep,
    RiskSettingsDep,
    RunningEngineDep,
    SessionDep,
    SettingsDep,
    SnapshotsDep,
)
from app.api.schemas.common import DEFAULT_PAGE_SIZE, LimitParam, OffsetParam, Page
from app.api.schemas.records import RiskEventOut, risk_event_out
from app.api.schemas.risk import (
    AccountIn,
    AccountOut,
    ControlsOut,
    KillSwitchIn,
    RiskLimitsIn,
    RiskLimitsOut,
    RiskOut,
)
from app.api.schemas.status import SnapshotOut
from app.api.views import limits_out
from app.db.repositories import RiskEventRepository
from app.engine.risk import RiskLimits

router = APIRouter(tags=["control"])


@router.get("/status", response_model=SnapshotOut)
async def get_status(snapshots: SnapshotsDep) -> SnapshotOut:
    """The whole picture of the system now: the same data the WebSocket sends first."""
    return snapshots.build()


# --- risk ---


@router.get("/risk", response_model=RiskOut)
async def get_risk(snapshots: SnapshotsDep, engine: EngineDep) -> RiskOut:
    return RiskOut(
        controls=snapshots.controls(),
        day=snapshots.day(),
        open_trades=None if engine is None else engine.guard.open_trades,
        open_exposure=None if engine is None else engine.guard.open_exposure,
    )


@router.put("/risk/limits", response_model=RiskLimitsOut)
async def set_risk_limits(body: RiskLimitsIn, risk: RiskSettingsDep) -> RiskLimitsOut:
    """Set the global limits. Works with or without the engine running, so they can be set before
    it is ever enabled. Today's result is kept: this is no way to reset a stop-loss."""
    limits = RiskLimits(
        max_stake=body.max_stake,
        max_concurrent_trades=body.max_concurrent_trades,
        max_exposure=body.max_exposure,
        max_chain_trades=body.max_chain_trades,
        daily_stop_loss=body.daily_stop_loss,
        daily_profit_target=body.daily_profit_target,
        reset_timezone=body.reset_timezone,
        reset_time=body.reset_time,
    )
    risk.set_limits(limits)
    return limits_out(limits)


@router.get("/risk/events", response_model=Page[RiskEventOut])
async def list_risk_events(
    session: SessionDep, limit: LimitParam = DEFAULT_PAGE_SIZE, offset: OffsetParam = 0
) -> Page[RiskEventOut]:
    """Every order a limit blocked and every other safety event, newest first."""
    repo = RiskEventRepository(session)
    rows = await repo.list_recent(limit=limit, offset=offset)
    return Page(
        items=[risk_event_out(e) for e in rows],
        total=await repo.count(),
        limit=limit,
        offset=offset,
    )


# --- kill switch ---


@router.post("/kill-switch", response_model=ControlsOut)
async def engage_kill_switch(
    engine: RunningEngineDep,
    snapshots: SnapshotsDep,
    body: Annotated[KillSwitchIn | None, Body()] = None,
) -> ControlsOut:
    """No order goes out from now on, follow-ups included. Repeating it is harmless."""
    engine.manager.engage_kill_switch(stop_chains=body.stop_chains if body else False)
    return snapshots.controls()


@router.delete("/kill-switch", response_model=ControlsOut)
async def release_kill_switch(engine: RunningEngineDep, snapshots: SnapshotsDep) -> ControlsOut:
    engine.manager.release_kill_switch()
    return snapshots.controls()


# --- account ---


@router.get("/account", response_model=AccountOut)
async def get_account(live: LiveDep, settings: SettingsDep) -> AccountOut:
    return AccountOut(
        account_type=live.account_type, real_trading_allowed=settings.quotex_allow_real
    )


@router.put("/account", response_model=AccountOut)
async def set_account(
    body: AccountIn, engine: RunningEngineDep, settings: SettingsDep
) -> AccountOut:
    """Switch between demo and real. Refused while a chain or trade is running; real also needs
    QUOTEX_ALLOW_REAL=true (decision D-15)."""
    await engine.switch_account(body.account_type)
    return AccountOut(
        account_type=engine.adapter.account_type, real_trading_allowed=settings.quotex_allow_real
    )
