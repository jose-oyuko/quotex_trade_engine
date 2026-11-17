"""The real engine is built with or without Telegram (decision D-71): nothing connects here."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.brokers.errors import BrokerError
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.domain.enums import AccountType, Broker
from app.engine.factory import build_engine
from app.events.bus import EventBus
from tests.api_support import settings_for


def quotex_only(tmp_path: Path) -> Settings:
    return settings_for(tmp_path, quotex_email="owner@example.com", quotex_password="not-a-secret")


def test_without_a_telegram_login_the_engine_is_built_with_signals_off(tmp_path: Path) -> None:
    engine = build_engine(quotex_only(tmp_path), EventBus(), TaskSupervisor())
    assert engine.listener is None and not engine.telegram_enabled
    assert engine.scheduler is not None  # the trading sessions need Quotex only


# --- the brokers that have logins (decision D-75); nothing connects here either ---


def test_with_only_quotex_s_login_only_quotex_is_built(tmp_path: Path) -> None:
    engine = build_engine(quotex_only(tmp_path), EventBus(), TaskSupervisor())
    assert set(engine.adapters) == {Broker.QUOTEX}


def test_with_only_deriv_s_login_only_deriv_is_built(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, deriv_app_id="1234", deriv_token_demo="demo-token")
    engine = build_engine(settings, EventBus(), TaskSupervisor())
    assert set(engine.adapters) == {Broker.DERIV}
    assert engine.account_type is AccountType.DEMO


def test_with_both_logins_both_brokers_are_built_side_by_side(tmp_path: Path) -> None:
    settings = settings_for(
        tmp_path,
        quotex_email="owner@example.com",
        quotex_password="not-a-secret",
        deriv_app_id="1234",
        deriv_token_demo="demo-token",
    )
    engine = build_engine(settings, EventBus(), TaskSupervisor())
    assert set(engine.adapters) == {Broker.QUOTEX, Broker.DERIV}


def test_without_any_broker_login_the_engine_is_not_built_and_says_what_is_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(BrokerError) as raised:
        build_engine(settings_for(tmp_path), EventBus(), TaskSupervisor())
    assert "No broker has a login" in str(raised.value)
    assert "Quotex email and password are not set" in str(raised.value)
    assert "Deriv app id and demo token are not set" in str(raised.value)
