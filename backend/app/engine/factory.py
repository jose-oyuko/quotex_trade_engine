"""Builds the real engine (real Quotex adapter, real Telegram) from the application settings."""

from __future__ import annotations

from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.engine.engine import Engine
from app.events.bus import EventBus
from app.quotex.factory import build_pyquotex_adapter
from app.telegram.factory import build_telethon_source


def build_engine(settings: Settings, bus: EventBus, tasks: TaskSupervisor) -> Engine:
    """Raises `QuotexError` / `TelegramNotConfiguredError` if a login is missing. The adapter
    starts on the DEMO account (decision D-15)."""
    clock = SystemClock()
    return Engine(
        adapter=build_pyquotex_adapter(settings, tasks=tasks, clock=clock, bus=bus),
        source=build_telethon_source(settings, clock=clock),
        bus=bus,
        clock=clock,
        tasks=tasks,
    )
