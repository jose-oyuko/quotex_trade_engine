"""Builds the snapshot: the whole picture of the system at one instant."""

from __future__ import annotations

from app.api.schemas.records import balance_out, chain_out, trade_out
from app.api.schemas.risk import ControlsOut, DayOut
from app.api.schemas.status import ConnectionOut, EngineStatus, SnapshotOut
from app.api.views import controls_out
from app.core.config import Settings
from app.engine.engine import Engine
from app.services.groups import EngineProvider
from app.services.live import LiveState


class SnapshotBuilder:
    def __init__(
        self, *, settings: Settings, version: str, live: LiveState, engine: EngineProvider
    ) -> None:
        self._settings = settings
        self._version = version
        self._live = live
        self._engine = engine

    def controls(self) -> ControlsOut:
        """The stored controls; with an engine, its guard's own answer for the switches (it can be
        a moment ahead of the events)."""
        engine = self._engine()
        if engine is None:
            return controls_out(self._live.controls)
        return controls_out(
            self._live.controls,
            kill_switch=engine.guard.kill_switch,
            paused=engine.guard.paused_groups,
        )

    def day(self) -> DayOut | None:
        engine = self._engine()
        if engine is None:
            return None
        account = self._live.account_type
        return DayOut(
            account_type=account,
            since=engine.guard.current_day_start,
            pnl=engine.guard.day_pnl(account),
        )

    def build(self) -> SnapshotOut:
        live = self._live
        engine: Engine | None = self._engine()
        balance = live.balance
        return SnapshotOut(
            version=self._version,
            environment=self._settings.environment,
            engine=EngineStatus(enabled=self._settings.engine_enabled, running=engine is not None),
            account_type=live.account_type,
            real_trading_allowed=self._settings.quotex_allow_real,
            connections={
                name: ConnectionOut(
                    connected=status.connected, detail=status.detail, since=status.since
                )
                for name, status in sorted(live.connections.items())
            },
            balance=balance_out(balance) if balance else None,
            controls=self.controls(),
            day=self.day(),
            open_chains=[
                chain_out(c) for c in sorted(live.chains.values(), key=lambda c: c.created_at)
            ],
            open_trades=[
                trade_out(t) for t in sorted(live.trades.values(), key=lambda t: t.created_at)
            ],
            last_event_at=live.last_event_at,
        )
