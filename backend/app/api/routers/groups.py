"""Groups: configuration CRUD, pause/resume, and per-group risk limits."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import (
    EngineDep,
    GroupsDep,
    LiveDep,
    RiskSettingsDep,
    RunningEngineDep,
)
from app.api.schemas.common import DEFAULT_PAGE_SIZE, LimitParam, OffsetParam, Page
from app.api.schemas.groups import GroupCreateIn, GroupOut, GroupSettingsIn, GroupUpdateIn
from app.api.schemas.risk import GroupRiskLimitsIn, GroupRiskLimitsOut
from app.api.views import group_limits_out, group_out
from app.engine.risk import GroupRiskLimits
from app.services.groups import GroupView, SettingsValues
from app.services.live import LiveState

router = APIRouter(prefix="/groups", tags=["groups"])


def _settings_values(settings: GroupSettingsIn) -> SettingsValues:
    return SettingsValues(
        parser=settings.parser,
        asset_suffix_mode=settings.asset_suffix_mode,
        timezone=settings.timezone,
        strategy=settings.strategy,
        base_stake=settings.base_stake,
        max_steps=settings.max_steps,
        multipliers=tuple(settings.multipliers),
        min_payout_pct=settings.min_payout_pct,
        allow_opposite_pair=settings.allow_opposite_pair,
    )


def _out(view: GroupView, engine: EngineDep, live: LiveState) -> GroupOut:
    group_id = view.group.id or 0
    if engine is not None:  # the engine's own answer is the freshest
        paused = group_id in engine.guard.paused_groups
        active = len(engine.manager.active_chains(group_id))
    else:
        paused = group_id in live.controls.paused_groups
        active = live.active_chains_of(group_id)
    return group_out(view, paused=paused, active_chains=active)


@router.get("", response_model=Page[GroupOut])
async def list_groups(
    groups: GroupsDep,
    engine: EngineDep,
    live: LiveDep,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
    offset: OffsetParam = 0,
) -> Page[GroupOut]:
    views = await groups.list()
    return Page(
        items=[_out(v, engine, live) for v in views[offset : offset + limit]],
        total=len(views),
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=GroupOut, status_code=201)
async def create_group(
    body: GroupCreateIn, response: Response, groups: GroupsDep, engine: EngineDep, live: LiveDep
) -> GroupOut:
    view = await groups.create(
        telegram_chat_id=body.telegram_chat_id,
        title=body.title,
        enabled=body.enabled,
        settings=_settings_values(body.settings),
    )
    response.headers["Location"] = f"/api/v1/groups/{view.group.id}"
    return _out(view, engine, live)


@router.get("/{group_id}", response_model=GroupOut)
async def get_group(group_id: int, groups: GroupsDep, engine: EngineDep, live: LiveDep) -> GroupOut:
    return _out(await groups.get(group_id), engine, live)


@router.put("/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: int, body: GroupUpdateIn, groups: GroupsDep, engine: EngineDep, live: LiveDep
) -> GroupOut:
    """Chains already running keep the settings they started with."""
    view = await groups.update(
        group_id, title=body.title, enabled=body.enabled, settings=_settings_values(body.settings)
    )
    return _out(view, engine, live)


@router.delete("/{group_id}", status_code=204)
async def delete_group(group_id: int, groups: GroupsDep) -> Response:
    """Only a group with no history can be deleted; otherwise disable it."""
    await groups.delete(group_id)
    return Response(status_code=204)


@router.post("/{group_id}/pause", response_model=GroupOut)
async def pause_group(
    group_id: int, groups: GroupsDep, engine: RunningEngineDep, live: LiveDep
) -> GroupOut:
    """New signals of the group are ignored (and say so); its running chains finish."""
    view = await groups.get(group_id)
    engine.manager.pause_group(group_id)
    return _out(view, engine, live)


@router.post("/{group_id}/resume", response_model=GroupOut)
async def resume_group(
    group_id: int, groups: GroupsDep, engine: RunningEngineDep, live: LiveDep
) -> GroupOut:
    view = await groups.get(group_id)
    engine.manager.resume_group(group_id)
    return _out(view, engine, live)


@router.get("/{group_id}/risk", response_model=GroupRiskLimitsOut)
async def get_group_risk(group_id: int, groups: GroupsDep, live: LiveDep) -> GroupRiskLimitsOut:
    await groups.get(group_id)
    return group_limits_out(live.controls.group_limits.get(group_id, GroupRiskLimits()))


@router.put("/{group_id}/risk", response_model=GroupRiskLimitsOut)
async def set_group_risk(
    group_id: int, body: GroupRiskLimitsIn, groups: GroupsDep, risk: RiskSettingsDep
) -> GroupRiskLimitsOut:
    """Works with or without the engine running, so limits can be set before it is enabled."""
    await groups.get(group_id)
    limits = GroupRiskLimits(
        max_stake=body.max_stake,
        daily_stop_loss=body.daily_stop_loss,
        daily_profit_target=body.daily_profit_target,
    )
    risk.set_group_limits(group_id, limits)
    return group_limits_out(limits)
