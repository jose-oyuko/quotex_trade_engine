"""`.env.example` is the owner's only list of settings: it must match what the code reads."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings

EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"
KEY = re.compile(r"^#?\s*([A-Z][A-Z0-9_]+)=", re.MULTILINE)


def documented_keys() -> set[str]:
    return set(KEY.findall(EXAMPLE.read_text(encoding="utf-8")))


def test_every_setting_is_documented_in_the_example() -> None:
    missing = {name.upper() for name in Settings.model_fields} - documented_keys()
    assert not missing, f"add these to .env.example: {sorted(missing)}"


def test_the_example_names_no_setting_that_does_not_exist() -> None:
    unknown = documented_keys() - {name.upper() for name in Settings.model_fields}
    assert not unknown, f".env.example mentions settings the code ignores: {sorted(unknown)}"


def test_the_example_loads_as_is_and_stays_safe(tmp_path: Path) -> None:
    """Copying it unchanged must give a working, safe setup: loopback, demo, trading off."""
    copy = tmp_path / ".env"
    copy.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    settings = Settings(_env_file=copy)  # type: ignore[call-arg]
    assert settings.host == "127.0.0.1" and settings.allow_public_bind is False
    assert settings.engine_enabled is False and settings.quotex_allow_real is False
    assert settings.quotex_email is None and settings.telegram_api_hash is None


def test_the_example_holds_no_real_looking_secret() -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    assert "you@example.com" in text  # placeholders only
    assert not re.search(r"^[A-Z_]*(PASSWORD|HASH)=\S", text, re.MULTILINE)  # nothing active
