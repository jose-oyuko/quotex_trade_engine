"""Builds the real engine (the brokers that have logins, real Telegram) from the settings."""

from __future__ import annotations

import structlog

from app.brokers.base import BrokerAdapter
from app.brokers.errors import BrokerError
from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.deriv.factory import build_deriv_adapter, check_deriv_account
from app.domain.enums import Broker
from app.engine.engine import Engine
from app.events.bus import EventBus
from app.quotex.factory import build_pyquotex_adapter
from app.telegram.factory import build_telethon_source
from app.telegram.source import TelegramNotConfiguredError, TelegramSource

log = structlog.get_logger()

__all__ = ["build_engine", "check_deriv_account"]


def build_engine(settings: Settings, bus: EventBus, tasks: TaskSupervisor) -> Engine:
    """One adapter per broker whose login is there: Quotex (email and password) and Deriv (app id
    and demo token), side by side (decision D-75). Raises `BrokerError` when neither has a login.
    Telegram is optional: without its login the engine starts with signals off (trading sessions
    still run, decision D-71). Every adapter starts on the DEMO account (decision D-15)."""
    clock = SystemClock()
    adapters: dict[Broker, BrokerAdapter] = {}
    missing: list[str] = []
    try:
        adapters[Broker.QUOTEX] = build_pyquotex_adapter(
            settings, tasks=tasks, clock=clock, bus=bus
        )
    except BrokerError as exc:
        missing.append(str(exc))
    try:
        adapters[Broker.DERIV] = build_deriv_adapter(settings, tasks=tasks, clock=clock, bus=bus)
    except BrokerError as exc:
        missing.append(str(exc))
    if not adapters:
        raise BrokerError("No broker has a login. " + " ".join(missing))
    for reason in missing:
        log.info("broker_off", reason=reason)
    source: TelegramSource | None
    try:
        source = build_telethon_source(settings, clock=clock)
    except TelegramNotConfiguredError as exc:
        log.warning("telegram_off", reason=str(exc))
        source = None
    return Engine(adapters=adapters, source=source, bus=bus, clock=clock, tasks=tasks)
