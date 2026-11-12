"""The real engine is built with or without Telegram (decision D-71): nothing connects here."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.engine.factory import build_engine
from app.events.bus import EventBus
from tests.api_support import settings_for


def quotex_only(tmp_path: Path) -> Settings:
    return settings_for(tmp_path, quotex_email="owner@example.com", quotex_password="not-a-secret")


def test_without_a_telegram_login_the_engine_is_built_with_signals_off(tmp_path: Path) -> None:
    engine = build_engine(quotex_only(tmp_path), EventBus(), TaskSupervisor())
    assert engine.listener is None and not engine.telegram_enabled
    assert engine.scheduler is not None  # the trading sessions need Quotex only
