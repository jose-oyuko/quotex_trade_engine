"""Stored secrets: they go in encrypted, never come out, and a wrong or missing key is explained."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.vault.crypto import generate_key
from tests.api_support import running_api

API = "/api/v1"
KEY = generate_key()
OTHER_KEY = generate_key()
PASSWORD = "my very private quotex password"


def stored_text(db_path: Path) -> str:
    with sqlite3.connect(db_path) as db:
        return " ".join(row[0] for row in db.execute("SELECT ciphertext FROM secrets"))


def by_name(body: dict[str, object]) -> dict[str, dict[str, object]]:
    items = body["items"]
    assert isinstance(items, list)
    return {item["name"]: item for item in items}


async def test_a_new_installation_lists_the_secrets_as_not_set(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        body = (await rig.client.get(f"{API}/secrets")).json()
        assert body["key"] == "ok"
        assert list(by_name(body)) == [
            "quotex_email",
            "quotex_password",
            "telegram_api_id",
            "telegram_api_hash",
        ]
        assert {i["name"]: i["group"] for i in body["items"]}["telegram_api_hash"] == "telegram"
        assert all(i["is_set"] is False and i["readable"] is False for i in body["items"])
        assert all(i["updated_at"] is None for i in body["items"])


async def test_a_secret_is_stored_encrypted_and_only_its_status_comes_back(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        put = await rig.client.put(f"{API}/secrets/quotex_password", json={"value": PASSWORD})
        assert put.status_code == 200
        assert put.json()["is_set"] is True and put.json()["readable"] is True
        assert PASSWORD not in put.text

        listed = await rig.client.get(f"{API}/secrets")
        item = by_name(listed.json())["quotex_password"]
        assert item["is_set"] is True and item["readable"] is True and item["updated_at"]
        assert by_name(listed.json())["quotex_email"]["is_set"] is False
        assert PASSWORD not in listed.text

        text = stored_text(rig.settings.database_path)
        assert text.startswith("v1.") and PASSWORD not in text

        # the application itself can read it back (the engine will, from Phase 12)
        assert await rig.app.state.vault.get("quotex_password") == PASSWORD


async def test_the_value_is_not_in_the_database_file_the_log_or_any_answer(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        answers = [
            (await rig.client.put(f"{API}/secrets/quotex_password", json={"value": PASSWORD})).text,
            (await rig.client.get(f"{API}/secrets")).text,
            (await rig.client.get(f"{API}/settings")).text,
            (await rig.client.get(f"{API}/status")).text,
            (await rig.client.get(f"{API}/health")).text,
        ]
        wrong = await rig.client.put(f"{API}/secrets/nope", json={"value": PASSWORD})
        answers.append(wrong.text)
        db_path = rig.settings.database_path
    raw = b"".join(p.read_bytes() for p in (db_path, Path(f"{db_path}-wal")) if p.exists())
    logs = capfd.readouterr()
    assert PASSWORD.encode() not in raw
    assert KEY.encode() not in raw
    for text in (*answers, logs.out, logs.err):
        assert PASSWORD not in text and KEY not in text
    assert "secret_stored" in logs.out + logs.err  # it is logged, by name only


async def test_replacing_and_removing_a_secret(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        await rig.client.put(f"{API}/secrets/quotex_email", json={"value": "  me@example.com "})
        assert await rig.app.state.vault.get("quotex_email") == "me@example.com"  # trimmed
        await rig.client.put(f"{API}/secrets/quotex_email", json={"value": "new@example.com"})
        assert await rig.app.state.vault.get("quotex_email") == "new@example.com"
        removed = await rig.client.delete(f"{API}/secrets/quotex_email")
        assert removed.status_code == 204
        assert (await rig.client.delete(f"{API}/secrets/quotex_email")).status_code == 204
        assert (
            by_name((await rig.client.get(f"{API}/secrets")).json())["quotex_email"]["is_set"]
            is False
        )
        assert await rig.app.state.vault.get("quotex_email") is None
        assert stored_text(rig.settings.database_path) == ""


@pytest.mark.parametrize(
    ("name", "value", "status", "code"),
    [
        ("not_a_secret", "x", 404, "unknown_secret"),
        ("quotex_password", "   ", 422, "invalid_secret"),
        ("quotex_password", "x" * 513, 422, "validation_error"),
        ("quotex_password", "bad\u0000value", 422, "invalid_secret"),
    ],
)
async def test_bad_names_and_values_are_refused_without_storing_anything(
    tmp_path: Path, name: str, value: str, status: int, code: str
) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        response = await rig.client.put(f"{API}/secrets/{name}", json={"value": value})
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert stored_text(rig.settings.database_path) == ""
        assert (await rig.client.delete(f"{API}/secrets/{name}")).status_code in (204, 404)


async def test_without_a_key_nothing_can_be_stored_and_the_reason_is_clear(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:  # no SECRET_KEY
        assert (await rig.client.get(f"{API}/secrets")).json()["key"] == "missing"
        response = await rig.client.put(f"{API}/secrets/quotex_password", json={"value": PASSWORD})
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "secret_key_missing" and "npm run key:create" in error["message"]
        assert stored_text(rig.settings.database_path) == ""


async def test_a_malformed_key_is_reported_not_a_crash(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key="not a real key") as rig:
        assert (await rig.client.get(f"{API}/secrets")).json()["key"] == "invalid"
        response = await rig.client.put(f"{API}/secrets/quotex_password", json={"value": PASSWORD})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "secret_key_invalid"
        assert "not a real key" not in response.text


async def test_a_different_key_makes_the_value_unreadable_never_wrong_and_it_can_be_replaced(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        await rig.client.put(f"{API}/secrets/quotex_password", json={"value": PASSWORD})

    async with running_api(tmp_path, secret_key=OTHER_KEY) as rig:  # the key was changed
        item = by_name((await rig.client.get(f"{API}/secrets")).json())["quotex_password"]
        assert item["is_set"] is True and item["readable"] is False
        # the application is told, not given something wrong
        from app.vault.errors import SecretUnreadableError

        with pytest.raises(SecretUnreadableError):
            await rig.app.state.vault.get("quotex_password")
        # typing it again with the new key fixes it
        fixed = await rig.client.put(f"{API}/secrets/quotex_password", json={"value": "again"})
        assert fixed.json()["readable"] is True
        assert await rig.app.state.vault.get("quotex_password") == "again"


async def test_the_stored_value_survives_a_restart_with_the_same_key(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        await rig.client.put(f"{API}/secrets/telegram_api_hash", json={"value": "abc123hash"})
    async with running_api(tmp_path, secret_key=KEY) as again:
        assert await again.app.state.vault.get("telegram_api_hash") == "abc123hash"


async def test_a_value_copied_into_another_row_is_unreadable(tmp_path: Path) -> None:
    """Someone with the database file cannot make one secret pose as another."""
    async with running_api(tmp_path, secret_key=KEY) as rig:
        await rig.client.put(f"{API}/secrets/quotex_password", json={"value": PASSWORD})
        with sqlite3.connect(rig.settings.database_path) as db:
            (cipher,) = db.execute("SELECT ciphertext FROM secrets").fetchone()
            db.execute(
                "INSERT INTO secrets (name, ciphertext, created_at, updated_at) "
                "VALUES ('telegram_api_hash', ?, '2026-01-01', '2026-01-01')",
                (cipher,),
            )
        body = (await rig.client.get(f"{API}/secrets")).json()
        assert by_name(body)["quotex_password"]["readable"] is True
        assert by_name(body)["telegram_api_hash"]["readable"] is False


async def test_the_secrets_need_a_login(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, logged_in=False) as rig:
        for method, path in (
            ("GET", "/secrets"),
            ("PUT", "/secrets/quotex_password"),
            ("DELETE", "/secrets/quotex_password"),
        ):
            response = await rig.client.request(method, f"{API}{path}", json={"value": "x"})
            assert response.status_code == 401, (method, path)


def test_the_documented_operations_do_not_include_a_way_to_read_a_value() -> None:
    from app.main import create_app
    from tests.api_support import settings_for

    document = create_app(settings_for(Path("."))).openapi()
    text = json.dumps(document)
    assert '"/api/v1/secrets/{name}"' in text
    methods = set(document["paths"]["/api/v1/secrets/{name}"])
    assert methods == {"put", "delete"}  # no GET of one secret
    schemas = document["components"]["schemas"]
    for model in ("SecretItemOut", "SecretsOut"):
        assert "value" not in schemas[model]["properties"]
