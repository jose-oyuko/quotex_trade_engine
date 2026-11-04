from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.domain.enums import AccountType
from app.quotex.errors import QuotexError, RealAccountNotAllowedError
from app.quotex.factory import build_pyquotex_adapter


def make(**env: object) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[call-arg, arg-type]


def test_quotex_defaults_are_safe() -> None:
    settings = make()
    assert settings.quotex_email is None and settings.quotex_password is None
    assert settings.quotex_host == "quotex.com"
    assert settings.quotex_allow_real is False
    assert settings.quotex_time_mode == "TIME"


def test_credentials_never_appear_in_repr_or_str() -> None:
    settings = make(quotex_email="me@example.com", quotex_password="hunter2-very-secret")
    text = repr(settings) + str(settings) + str(settings.model_dump())
    assert "hunter2-very-secret" not in text
    assert "me@example.com" not in text
    assert settings.quotex_password is not None
    assert settings.quotex_password.get_secret_value() == "hunter2-very-secret"


def test_credentials_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUOTEX_EMAIL", "env@example.com")
    monkeypatch.setenv("QUOTEX_PASSWORD", "pw")
    monkeypatch.setenv("QUOTEX_HOST", "Quotex.IO")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.quotex_host == "quotex.io"
    assert settings.quotex_email is not None
    assert settings.quotex_email.get_secret_value() == "env@example.com"


@pytest.mark.parametrize(
    "host", ["https://quotex.com", "quotex.com/trade", "quotex.com:443", "", "a b.com"]
)
def test_the_quotex_host_must_be_a_bare_domain(host: str) -> None:
    with pytest.raises(ValidationError, match="bare domain"):
        make(quotex_host=host)


def test_the_time_mode_must_be_known() -> None:
    with pytest.raises(ValidationError):
        make(quotex_time_mode="SOON")


def test_the_factory_needs_credentials() -> None:
    with pytest.raises(QuotexError, match="QUOTEX_EMAIL"):
        build_pyquotex_adapter(make(), tasks=TaskSupervisor(), clock=SystemClock())


def test_the_factory_builds_a_demo_adapter_that_cannot_go_real() -> None:
    settings = make(quotex_email="a@b.c", quotex_password="pw")
    adapter = build_pyquotex_adapter(settings, tasks=TaskSupervisor(), clock=SystemClock())
    assert adapter.account_type is AccountType.DEMO
    with pytest.raises(RealAccountNotAllowedError):
        build_pyquotex_adapter(
            settings, tasks=TaskSupervisor(), clock=SystemClock(), account_type=AccountType.REAL
        )


async def test_the_factory_allows_real_only_when_enabled() -> None:
    settings = make(quotex_email="a@b.c", quotex_password="pw").model_copy(
        update={"quotex_allow_real": True}
    )
    adapter = build_pyquotex_adapter(settings, tasks=TaskSupervisor(), clock=SystemClock())
    await adapter.set_account_type(AccountType.REAL)  # not connected: only records the choice
    assert adapter.account_type is AccountType.REAL


@pytest.mark.parametrize("email", ["", "   "])
def test_blank_credentials_count_as_missing(email: str) -> None:
    """A freshly copied .env has `QUOTEX_EMAIL=` with nothing after it."""
    settings = make(quotex_email=email, quotex_password="")
    with pytest.raises(QuotexError, match="QUOTEX_EMAIL"):
        build_pyquotex_adapter(settings, tasks=TaskSupervisor(), clock=SystemClock())
