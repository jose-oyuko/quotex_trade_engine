"""Records and live state -> response shapes."""

from __future__ import annotations

from app.api.schemas.groups import GroupOut, GroupSettingsOut
from app.api.schemas.risk import ControlsOut, GroupRiskLimitsOut, RiskLimitsOut
from app.api.schemas.sessions import SessionOut, SessionRunOut, SessionStrategyOut
from app.domain.records import GroupSettingsRecord, SessionRunRecord
from app.engine.engine import Engine
from app.engine.risk import GroupRiskLimits, RiskLimits
from app.services.groups import GroupView
from app.services.live import Controls
from app.services.sessions import SessionView


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


def run_out(run: SessionRunRecord) -> SessionRunOut:
    return SessionRunOut(
        id=run.id,
        session_id=run.session_id,
        started_by=run.started_by,
        account_type=run.account_type,
        started_at=run.started_at,
        window_end=run.window_end,
        state=run.state,
        updated_at=run.updated_at,
        pairs_opened=run.pairs_opened,
        rounds_skipped=run.rounds_skipped,
        lopsided_pairs=run.lopsided_pairs,
        profit=run.profit,
        ended_at=run.ended_at,
        end_reason=run.end_reason,
        note=run.note,
    )


def session_out(view: SessionView, engine: Engine | None) -> SessionOut:
    record = view.session
    if record.id is None:
        raise ValueError("a stored session always has an id")
    active = engine.scheduler.active_run_of(record.id) if engine is not None else None
    settings = view.settings
    return SessionOut(
        id=record.id,
        name=record.name,
        enabled=record.enabled,
        group_id=record.group_id,
        asset=record.asset,
        duration_s=record.duration_s,
        start_time=record.start_time,
        end_time=record.end_time,
        timezone=record.timezone,
        repeat=record.repeat,
        weekdays=list(record.weekdays),
        pause_s=record.pause_s,
        profit_target=record.profit_target,
        loss_limit=record.loss_limit,
        max_pairs=record.max_pairs,
        mode=record.mode,
        max_open_pairs=record.max_open_pairs,
        broker=record.broker,
        strategy=None
        if settings is None
        else SessionStrategyOut(
            strategy=settings.strategy,
            base_stake=settings.base_stake,
            max_steps=settings.max_steps,
            multipliers=list(settings.multipliers),
            min_payout_pct=settings.min_payout_pct,
        ),
        next_window_start=view.next_window.start if view.next_window else None,
        next_window_end=view.next_window.end if view.next_window else None,
        warnings=list(view.warnings),
        active_run=run_out(active) if active is not None else None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def group_out(view: GroupView, *, paused: bool, active_chains: int) -> GroupOut:
    group = view.group
    if group.id is None:
        raise ValueError("a stored group always has an id")
    if group.telegram_chat_id is None:
        raise ValueError("only Telegram groups are shown as groups")
    return GroupOut(
        id=group.id,
        telegram_chat_id=group.telegram_chat_id,
        title=group.title,
        enabled=group.enabled,
        broker=group.broker,
        created_at=group.created_at,
        updated_at=group.updated_at,
        settings=settings_out(view.settings) if view.settings else None,
        paused=paused,
        active_chains=active_chains,
    )
