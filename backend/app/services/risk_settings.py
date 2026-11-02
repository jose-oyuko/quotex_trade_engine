"""Setting the risk limits, with or without the trading engine running.

Limits have to be settable *before* the engine is ever enabled (that is the safe order: limits
first, then trading), so when there is no engine the change is stored through the event bus like any
other setting and the engine picks it up when it starts. With an engine the guard itself is told.
"""

from __future__ import annotations

from app.core.clock import Clock
from app.engine.risk import GroupRiskLimits, RiskLimits, group_limits_setting, limits_setting
from app.events.bus import EventBus
from app.events.types import SettingChanged
from app.services.groups import EngineProvider
from app.services.live import LiveState


class RiskSettingsService:
    def __init__(
        self, bus: EventBus, clock: Clock, live: LiveState, engine: EngineProvider
    ) -> None:
        self._bus = bus
        self._clock = clock
        self._live = live
        self._engine = engine

    def set_limits(self, limits: RiskLimits) -> None:
        now = self._clock.now()
        setting = limits_setting(limits, now)
        if (engine := self._engine()) is not None:
            engine.guard.set_limits(limits)  # publishes the setting itself
        else:
            self._bus.publish(SettingChanged(occurred_at=now, setting=setting))
        self._live.apply_setting(setting)  # so the very next read already shows it

    def set_group_limits(self, group_id: int, limits: GroupRiskLimits) -> None:
        now = self._clock.now()
        setting = group_limits_setting(group_id, limits, now)
        if (engine := self._engine()) is not None:
            engine.guard.set_group_limits(group_id, limits)
        else:
            self._bus.publish(SettingChanged(occurred_at=now, setting=setting))
        self._live.apply_setting(setting)
