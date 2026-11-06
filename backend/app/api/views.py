"""Records and live state -> response shapes."""

from __future__ import annotations

from app.api.schemas.groups import GroupOut, GroupSettingsOut
from app.api.schemas.risk import ControlsOut, GroupRiskLimitsOut, RiskLimitsOut
from app.domain.records import GroupSettingsRecord
from app.engine.risk import GroupRiskLimits, RiskLimits
from app.services.groups import GroupView
from app.services.live import Controls


def limits_out(limits: RiskLimits) -> RiskLimitsOut:
    return RiskLimitsOut(
        max_stake=limits.max_stake,
        max_concurrent_trades=limits.max_concurrent_trades,
        max_exposure=limits.max_exposure,
        max_chain_trades=limits.max_chain_trades,
        daily_stop_loss=limits.daily_stop_loss,
        daily_profit_target=limits.daily_profit_target,
        reset_timezone=limits.reset_timezone,
        reset_time=limits.reset_time.strftime("%H:%M"),
    )


def group_limits_out(limits: GroupRiskLimits) -> GroupRiskLimitsOut:
    return GroupRiskLimitsOut(
        max_stake=limits.max_stake,
        daily_stop_loss=limits.daily_stop_loss,
        daily_profit_target=limits.daily_profit_target,
    )


def controls_out(
    controls: Controls, *, kill_switch: bool | None = None, paused: frozenset[int] | None = None
) -> ControlsOut:
    """`kill_switch` and `paused` override the stored view with the guard's own, fresher answer."""
    return ControlsOut(
        kill_switch=controls.kill_switch if kill_switch is None else kill_switch,
        paused_groups=sorted(controls.paused_groups if paused is None else paused),
        limits=limits_out(controls.limits),
        group_limits={gid: group_limits_out(lim) for gid, lim in controls.group_limits.items()},
    )


def settings_out(settings: GroupSettingsRecord) -> GroupSettingsOut:
    return GroupSettingsOut(
        parser=settings.parser,
        asset_suffix_mode=settings.asset_suffix_mode,
        timezone=settings.timezone,
        strategy=settings.strategy,
        base_stake=settings.base_stake,
        max_steps=settings.max_steps,
        multipliers=list(settings.multipliers),
        min_payout_pct=settings.min_payout_pct,
        allow_opposite_pair=settings.allow_opposite_pair,
        updated_at=settings.updated_at,
    )


def group_out(view: GroupView, *, paused: bool, active_chains: int) -> GroupOut:
    group = view.group
    if group.id is None:
        raise ValueError("a stored group always has an id")
    return GroupOut(
        id=group.id,
        telegram_chat_id=group.telegram_chat_id,
        title=group.title,
        enabled=group.enabled,
        created_at=group.created_at,
        updated_at=group.updated_at,
        settings=settings_out(view.settings) if view.settings else None,
        paused=paused,
        active_chains=active_chains,
    )
