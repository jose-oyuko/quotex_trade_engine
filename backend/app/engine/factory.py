"""Builds the real engine (real Quotex adapter, real Telegram) from the application settings."""

from __future__ import annotations

import structlog

from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.engine.engine import Engine
from app.events.bus import EventBus
from app.quotex.factory import build_pyquotex_adapter
from app.telegram.factory import build_telethon_source
from app.telegram.source import TelegramNotConfiguredError, TelegramSource

log = structlog.get_logger()


def build_engine(settings: Settings, bus: EventBus, tasks: TaskSupervisor) -> Engine:
    """Raises `QuotexError` if the Quotex login is missing. Telegram is optional: without its login
    the engine starts with signals off (trading sessions need Quotex only, decision D-71). The
    adapter starts on the DEMO account (decision D-15)."""
    clock = SystemClock()
    adapter = build_pyquotex_adapter(settings, tasks=tasks, clock=clock, bus=bus)
    source: TelegramSource | None
    try:
        source = build_telethon_source(settings, clock=clock)
    except TelegramNotConfiguredError as exc:
        log.warning("telegram_off", reason=str(exc))
        source = None
    return Engine(adapter=adapter, source=source, bus=bus, clock=clock, tasks=tasks)
