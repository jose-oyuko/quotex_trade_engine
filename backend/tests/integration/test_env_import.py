"""Moving the old `.env` logins into the encrypted store: through the dashboard's API, the command
(`npm run env:import`) and the command-line tools that now share the dashboard's store."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.engine.logins import resolve_settings
from app.telegram.fake import FakeTelegramSource
from app.vault.crypto import generate_key
from scripts import env_import, telegram_cli
from scripts._store import StoreUnavailableError, open_store, with_stored_logins
from tests.api_support import migrate, running_api, settings_for
from tests.signal_support import ManualClock

API = "/api/v1"
KEY = generate_key()
OLD = {
    "quotex_email": "env@example.com",
    "quotex_password": "env-password-123",
    "telegram_api_id": 4242,
    "telegram_api_hash": "envhash-abcdef",
}
OLD_ENV = (
    "HOST=127.0.0.1\r\nQUOTEX_EMAIL=env@example.com\r\nQUOTEX_PASSWORD=env-password-123\r\n"
    "TELEGRAM_API_ID=4242\r\nTELEGRAM_API_HASH=envhash-abcdef\r\nENGINE_ENABLED=true\r\n"
    "QUOTEX_ALLOW_REAL=true\r\n# a note of mine\r\nPORT=8000\r\n"
)


def stored_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as db:
        return {row[0] for row in db.execute("SELECT name FROM secrets")}


# --- the dashboard's API -----------------------------------------------------------------------


async def test_the_dashboard_lists_what_env_still_holds_and_moves_it_without_a_value_showing(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, secret_key=KEY, **OLD) as rig:
        listed = (await rig.client.get(f"{API}/settings/env-logins")).json()["items"]
        assert [(i["label"], i["in_env"], i["stored"]) for i in listed] == [
            ("Quotex email", True, False),
            ("Quotex password", True, False),
            ("Telegram API id", True, False),
            ("Telegram API hash", True, False),
        ]
        response = await rig.client.post(f"{API}/settings/env-logins/import")
        assert response.status_code == 200
        body = response.json()
        assert body["imported"] == [
            "Quotex email",
            "Quotex password",
            "Telegram API id",
            "Telegram API hash",
        ]
        assert all(i["stored"] for i in body["items"])
        for secret in ("env@example.com", "env-password-123", "envhash-abcdef", "4242"):
            assert secret not in response.text
        assert stored_names(rig.settings.database_path) == {
            "quotex_email",
            "quotex_password",
            "telegram_api_id",
            "telegram_api_hash",
        }
        assert await rig.app.state.vault.get("quotex_password") == "env-password-123"
        assert await rig.app.state.vault.get("telegram_api_id") == "4242"


async def test_moving_never_overwrites_a_login_that_is_already_stored(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, quotex_email="env@example.com") as rig:
        await rig.client.put(f"{API}/secrets/quotex_email", json={"value": "stored@example.com"})
        body = (await rig.client.post(f"{API}/settings/env-logins/import")).json()
        assert body["imported"] == []
        assert await rig.app.state.vault.get("quotex_email") == "stored@example.com"
        again = (await rig.client.post(f"{API}/settings/env-logins/import")).json()
        assert again["imported"] == []  # harmless twice


async def test_with_nothing_in_env_there_is_nothing_to_move(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        listed = (await rig.client.get(f"{API}/settings/env-logins")).json()["items"]
        assert not any(i["in_env"] for i in listed)
        assert (await rig.client.post(f"{API}/settings/env-logins/import")).json()["imported"] == []


async def test_without_a_key_nothing_is_moved_and_the_reason_is_clear(tmp_path: Path) -> None:
    async with running_api(tmp_path, quotex_email="env@example.com") as rig:  # no SECRET_KEY
        response = await rig.client.post(f"{API}/settings/env-logins/import")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "secret_key_missing"
        assert stored_names(rig.settings.database_path) == set()


async def test_the_engine_prefers_the_stored_copy_once_it_is_moved(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, quotex_email="env@example.com") as rig:
        await rig.client.post(f"{API}/settings/env-logins/import")
        await rig.client.put(f"{API}/secrets/quotex_email", json={"value": "changed@example.com"})
        resolved = await resolve_settings(
            rig.app.state.settings, rig.app.state.vault, allow_real=False
        )
        assert resolved.quotex_email is not None
        assert resolved.quotex_email.get_secret_value() == "changed@example.com"


async def test_the_env_import_routes_need_a_login(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, logged_in=False) as rig:
        assert (await rig.client.get(f"{API}/settings/env-logins")).status_code == 401
        assert (await rig.client.post(f"{API}/settings/env-logins/import")).status_code == 401


# --- the command -------------------------------------------------------------------------------


def test_tidy_removes_the_values_and_keeps_everything_else_exactly() -> None:
    tidied = env_import.tidy(OLD_ENV, set(OLD))
    assert "env-password-123" not in tidied and "envhash-abcdef" not in tidied
    assert "env@example.com" not in tidied and "4242" not in tidied
    assert "HOST=127.0.0.1\r\n" in tidied and "PORT=8000\r\n" in tidied
    assert "# a note of mine\r\n" in tidied  # comments and Windows line endings stay
    assert "\n" not in tidied.replace("\r\n", "")
    assert "# ENGINE_ENABLED is no longer read" in tidied
    assert "# QUOTEX_ALLOW_REAL is no longer read" in tidied
    assert "# QUOTEX_EMAIL=   (moved to the encrypted store)\r\n" in tidied


def test_tidy_leaves_a_login_that_was_not_moved_alone() -> None:
    tidied = env_import.tidy(OLD_ENV, {"quotex_email"})
    assert "QUOTEX_PASSWORD=env-password-123\r\n" in tidied
    assert "QUOTEX_EMAIL=env@example.com" not in tidied


def test_env_value_reads_the_last_active_line_and_ignores_comments() -> None:
    text = "# ENGINE_ENABLED=true\nENGINE_ENABLED=false\nENGINE_ENABLED='true'\n"
    assert env_import.env_value(text, "ENGINE_ENABLED") == "true"
    assert env_import.env_value("# ENGINE_ENABLED=true\n", "ENGINE_ENABLED") is None


async def prepared(tmp_path: Path, env_text: str, **settings: Any) -> tuple[Any, Path]:
    config = settings_for(tmp_path, secret_key=KEY, **settings)
    await migrate(config)
    env_file = tmp_path / ".env"
    env_file.write_bytes(env_text.encode("utf-8"))
    return config, env_file


async def test_the_command_moves_the_logins_tidies_the_file_and_leaves_the_engine_on(
    tmp_path: Path,
) -> None:
    config, env_file = await prepared(tmp_path, OLD_ENV, **OLD)
    said: list[str] = []
    assert await env_import.run_import(config, env_file, yes=True, say=said.append) == 0
    text = env_file.read_bytes().decode()
    assert text == env_import.tidy(OLD_ENV, set(OLD))
    for secret in ("env-password-123", "envhash-abcdef", "env@example.com"):
        assert secret not in text and all(secret not in line for line in said)

    store = await open_store(config)
    try:
        assert await store.vault.get("quotex_email") == "env@example.com"
        assert await store.flags.desired() is True  # ENGINE_ENABLED=true was honoured, once
        assert await store.flags.allow_real() is None  # real money is never carried over
    finally:
        await store.close()
    joined = " ".join(said)
    assert "NOT carried over" in joined and "left running" in joined


async def test_the_command_asks_first_and_changes_nothing_on_no(tmp_path: Path) -> None:
    config, env_file = await prepared(tmp_path, OLD_ENV, **OLD)
    said: list[str] = []
    code = await env_import.run_import(
        config, env_file, yes=False, ask=lambda _: "n", say=said.append
    )
    assert code == 1 and env_file.read_bytes().decode() == OLD_ENV
    store = await open_store(config)
    try:
        assert not await store.vault.has("quotex_email")
    finally:
        await store.close()


async def test_the_command_says_when_there_is_nothing_to_do(tmp_path: Path) -> None:
    config, env_file = await prepared(tmp_path, "HOST=127.0.0.1\r\n")
    said: list[str] = []
    assert await env_import.run_import(config, env_file, yes=True, say=said.append) == 0
    assert "Nothing to move" in said[0]
    assert env_file.read_bytes().decode() == "HOST=127.0.0.1\r\n"


async def test_the_command_does_not_overrule_an_engine_decision_made_on_the_dashboard(
    tmp_path: Path,
) -> None:
    config, env_file = await prepared(tmp_path, "ENGINE_ENABLED=true\r\n")
    store = await open_store(config)
    try:
        await store.flags.set_desired(False)  # the owner stopped it on the dashboard
    finally:
        await store.close()
    await env_import.run_import(config, env_file, yes=True, say=lambda _: None)
    store = await open_store(config)
    try:
        assert await store.flags.desired() is False
    finally:
        await store.close()


async def test_the_command_explains_a_missing_key_or_database(tmp_path: Path) -> None:
    no_db = settings_for(tmp_path / "none", secret_key=KEY)
    said: list[str] = []
    assert await env_import.run_import(no_db, tmp_path / ".env", yes=True, say=said.append) == 1
    assert "npm start" in said[0]

    _, env_file = await prepared(tmp_path / "keyless", OLD_ENV)
    keyless = settings_for(tmp_path / "keyless", **OLD)  # same database, no SECRET_KEY
    said.clear()
    assert await env_import.run_import(keyless, env_file, yes=True, say=said.append) == 1
    assert "SECRET_KEY" in said[0] and env_file.read_bytes().decode() == OLD_ENV


# --- the command-line tools share the store ----------------------------------------------------


async def test_the_tools_see_the_logins_stored_on_the_dashboard(tmp_path: Path) -> None:
    config = settings_for(tmp_path, secret_key=KEY, quotex_email="env@example.com")
    await migrate(config)
    store = await open_store(config)
    try:
        await store.vault.put("quotex_email", "stored@example.com")
        await store.vault.put("telegram_api_id", "777")
    finally:
        await store.close()
    resolved = await with_stored_logins(config)
    assert resolved.quotex_email is not None
    assert resolved.quotex_email.get_secret_value() == "stored@example.com"
    assert resolved.telegram_api_id == 777


async def test_without_a_usable_store_the_tools_use_env_as_before(tmp_path: Path) -> None:
    config = settings_for(tmp_path / "fresh", quotex_email="env@example.com")  # no database
    assert await with_stored_logins(config) is config
    with pytest.raises(StoreUnavailableError, match="npm start"):
        await open_store(config)


async def test_the_telegram_command_stores_its_login_where_the_dashboard_finds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = settings_for(
        tmp_path, secret_key=KEY, telegram_api_id=99, telegram_api_hash="the-hash"
    )
    await migrate(config)
    fake = FakeTelegramSource(ManualClock(), authorized=False, login_code="12345")
    monkeypatch.setattr(telegram_cli, "new_login_source", lambda *a, **k: fake)
    monkeypatch.setattr(telegram_cli, "Settings", lambda: config)
    answers = iter(["+254712345678", "12345"])

    async def ask(prompt: str) -> str:
        return next(answers)

    monkeypatch.setattr(telegram_cli, "ask", ask)
    code = await telegram_cli.run(argparse.Namespace(command="login"))
    assert code == 0
    assert "stored, encrypted" in capsys.readouterr().out

    store = await open_store(config)
    try:
        assert await store.vault.get("telegram_session") == "fake-session-for-+254712345678"
        assert await store.vault.get("telegram_phone") == "+254712345678"
    finally:
        await store.close()
    assert stored_names(config.database_path) >= {"telegram_session", "telegram_phone"}
