from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, is_loopback_host


def make(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[arg-type]


def test_defaults_are_safe() -> None:
    settings = make()
    assert settings.host == "127.0.0.1"
    assert settings.allow_public_bind is False


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5"])
def test_loopback_hosts_are_accepted(host: str) -> None:
    assert make(host=host).host == host


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com", "::"])  # noqa: S104
def test_public_bind_is_refused_without_flag(host: str) -> None:
    with pytest.raises(ValidationError, match="Refusing to listen"):
        make(host=host)


def test_public_bind_allowed_with_explicit_flag() -> None:
    settings = make(host="0.0.0.0", allow_public_bind=True)  # type: ignore[arg-type]  # noqa: S104
    assert settings.host == "0.0.0.0"  # noqa: S104


def test_public_bind_refused_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST", "0.0.0.0")  # noqa: S104
    with pytest.raises(ValidationError, match="ALLOW_PUBLIC_BIND"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_is_loopback_host() -> None:
    assert is_loopback_host("LOCALHOST")
    assert not is_loopback_host("not a host")


def test_an_old_engine_or_real_money_line_in_env_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ENGINE_ENABLED and QUOTEX_ALLOW_REAL are gone (decisions D-63, D-64): the engine is
    started and real money allowed on the dashboard, with the password. An old line does neither."""
    env = tmp_path / ".env"
    env.write_text("ENGINE_ENABLED=true\nQUOTEX_ALLOW_REAL=true\n", encoding="utf-8")
    settings = Settings(_env_file=env)  # type: ignore[call-arg]
    assert settings.quotex_allow_real is False and not hasattr(settings, "engine_enabled")
    monkeypatch.setenv("QUOTEX_ALLOW_REAL", "true")
    monkeypatch.setenv("ENGINE_ENABLED", "true")
    assert Settings(_env_file=None).quotex_allow_real is False  # type: ignore[call-arg]
    # the application itself sets it (it does, from the owner's stored permission)
    allowed = Settings(_env_file=None).model_copy(update={"quotex_allow_real": True})  # type: ignore[call-arg]
    assert allowed.quotex_allow_real is True
