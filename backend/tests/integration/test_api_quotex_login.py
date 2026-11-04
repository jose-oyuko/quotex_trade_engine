"""Logging in to Quotex from the dashboard, with the e-mailed PIN, on a fake login."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.engine.engine import Engine
from app.events.bus import EventBus
from app.quotex.base import LoginRequest
from app.quotex.errors import QuotexConnectionError
from app.quotex.fake import FakeQuotexLogin
from app.services import quotex_login
from app.vault.crypto import generate_key
from tests.api_support import ApiRig, FakeParts, fake_builder, running_api

API = "/api/v1"
KEY = generate_key()
EMAIL = "me@example.com"
PASSWORD = "my quotex password"
SESSION = '{"cookies": "c=1", "token": "tok-123-secret", "user_agent": "test"}'


class Logins:
    """The logins the service starts, one per call to the factory, scripted by the test."""

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.made: list[FakeQuotexLogin] = []

    def __call__(self, request: LoginRequest) -> FakeQuotexLogin:
        login = FakeQuotexLogin(request, session=SESSION, **self.options)
        self.made.append(login)
        return login

    @property
    def last(self) -> FakeQuotexLogin:
        return self.made[-1]


async def store(rig: ApiRig, email: str = EMAIL, password: str = PASSWORD) -> None:
    for name, value in (("quotex_email", email), ("quotex_password", password)):
        assert (await rig.client.put(f"{API}/secrets/{name}", json={"value": value})).is_success


async def post(rig: ApiRig, path: str, body: dict[str, Any] | None = None) -> Any:
    return await rig.client.post(f"{API}/quotex/{path}", json=body or {})


async def status(rig: ApiRig) -> dict[str, Any]:
    body: dict[str, Any] = (await rig.client.get(f"{API}/quotex/login")).json()
    return body


def stored(rig: ApiRig, name: str) -> str | None:
    with sqlite3.connect(rig.settings.database_path) as db:
        row = db.execute("SELECT ciphertext FROM secrets WHERE name = ?", (name,)).fetchone()
    return None if row is None else str(row[0])


# --- the plain login ---------------------------------------------------------------------------


async def test_a_new_installation_is_logged_out_and_needs_the_email_and_password_first(
    tmp_path: Path,
) -> None:
    logins = Logins()
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        body = await status(rig)
        assert body["state"] == "logged_out" and body["configured"] is False
        refused = await post(rig, "login/start")
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "quotex_not_configured"
        assert logins.made == []
        await store(rig)
        assert (await status(rig))["configured"] is True


async def test_logging_in_stores_the_session_encrypted_and_uses_the_stored_credentials(
    tmp_path: Path,
) -> None:
    logins = Logins()
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        await store(rig)
        response = await post(rig, "login/start")
        assert response.status_code == 200 and response.json()["state"] == "logged_in"
        request = logins.last.request
        assert (request.email, request.password, request.host) == (EMAIL, PASSWORD, "quotex.com")

        sealed = stored(rig, "quotex_session")
        assert sealed is not None and sealed.startswith("v1.") and "tok-123" not in sealed
        assert await rig.app.state.vault.get("quotex_session") == SESSION
        assert (await status(rig))["state"] == "logged_in"
        # the application's own entry: the secrets API neither lists nor sets it
        names = {i["name"] for i in (await rig.client.get(f"{API}/secrets")).json()["items"]}
        assert "quotex_session" not in names
        put = await rig.client.put(f"{API}/secrets/quotex_session", json={"value": "x"})
        assert put.status_code == 404


async def test_the_env_credentials_are_enough_to_log_in(tmp_path: Path) -> None:
    logins = Logins()
    async with running_api(
        tmp_path,
        secret_key=KEY,
        quotex_login=logins,
        quotex_email="env@example.com",
        quotex_password="env-pw",
    ) as rig:
        assert (await post(rig, "login/start")).json()["state"] == "logged_in"
        assert logins.last.request.email == "env@example.com"


async def test_a_refused_login_comes_back_as_logged_out_with_the_reason(tmp_path: Path) -> None:
    logins = Logins(
        fail_with=QuotexConnectionError("Quotex did not accept the login: wrong password")
    )
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        await store(rig)
        response = await post(rig, "login/start")
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "logged_out" and "wrong password" in body["message"]
        assert stored(rig, "quotex_session") is None
        assert (await status(rig))["message"] == body["message"]  # still there after a reload


async def test_cloudflares_refusal_is_explained_in_words_not_a_crash(tmp_path: Path) -> None:
    from app.quotex.pyquotex_client import explain_connect_error

    message = explain_connect_error(
        AttributeError("'Response' object has no attribute 'reason_phrase'")
    )
    logins = Logins(fail_with=QuotexConnectionError(message))
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        await store(rig)
        body = (await post(rig, "login/start")).json()
        assert "Cloudflare" in body["message"] and "not a wrong password" in body["message"]
        assert "reason_phrase" not in body["message"]


# --- the PIN -----------------------------------------------------------------------------------


async def test_a_login_that_needs_a_pin_waits_for_it_and_finishes_with_it(tmp_path: Path) -> None:
    logins = Logins(pin="123456")
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        await store(rig)
        started = await post(rig, "login/start")
        body = started.json()
        assert started.status_code == 200 and body["state"] == "pin_needed"
        assert body["pin_prompt"] == "Enter the PIN we just sent to your email"
        # a page reload still shows the PIN box
        again = await status(rig)
        assert again["state"] == "pin_needed" and again["pin_prompt"] == body["pin_prompt"]
        assert stored(rig, "quotex_session") is None  # nothing is stored before the PIN

        done = await post(rig, "login/pin", {"pin": " 123456 "})
        assert done.status_code == 200 and done.json()["state"] == "logged_in"
        assert logins.last.pins_seen == ["123456"]
        assert stored(rig, "quotex_session") is not None


async def test_a_wrong_pin_ends_the_login_with_the_reason_and_it_can_be_started_again(
    tmp_path: Path,
) -> None:
    logins = Logins(pin="123456")
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        await store(rig)
        await post(rig, "login/start")
        wrong = await post(rig, "login/pin", {"pin": "000000"})
        body = wrong.json()
        assert wrong.status_code == 200 and body["state"] == "logged_out"
        assert "Wrong PIN" in body["message"]
        assert stored(rig, "quotex_session") is None

        # the owner starts again: Quotex sends a new PIN
        assert (await post(rig, "login/start")).json()["state"] == "pin_needed"
        assert (await post(rig, "login/pin", {"pin": "123456"})).json()["state"] == "logged_in"


@pytest.mark.parametrize("pin", ["abc", "12 34", "12.5", "-1", ""])
async def test_a_pin_that_is_not_digits_is_refused_and_the_login_keeps_waiting(
    tmp_path: Path, pin: str
) -> None:
    logins = Logins(pin="123456")
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        await store(rig)
        await post(rig, "login/start")
        response = await post(rig, "login/pin", {"pin": pin})
        assert response.status_code == 422
        assert (await status(rig))["state"] == "pin_needed"
        assert logins.last.pins_seen == []


async def test_a_pin_when_none_is_wanted_is_refused(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, quotex_login=Logins()) as rig:
        response = await post(rig, "login/pin", {"pin": "123456"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "quotex_login_step"


async def test_a_pin_nobody_types_is_given_up_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(quotex_login, "PIN_WAIT_S", 0.05)
    logins = Logins(pin="123456")
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        await store(rig)
        await post(rig, "login/start")
        await asyncio.sleep(0.3)
        body = await status(rig)
        assert body["state"] == "logged_out" and "not typed in time" in body["message"]
        assert (await post(rig, "login/pin", {"pin": "123456"})).status_code == 409


async def test_cancelling_a_login_that_waits_for_the_pin_drops_it(tmp_path: Path) -> None:
    logins = Logins(pin="123456")
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        await store(rig)
        await post(rig, "login/start")
        cancelled = await post(rig, "login/cancel")
        assert cancelled.json()["state"] == "logged_out" and cancelled.json()["message"] is None
        assert (await post(rig, "login/pin", {"pin": "123456"})).status_code == 409
        assert (await post(rig, "login/cancel")).status_code == 200  # harmless twice
        assert rig.app.state.tasks.running >= 0


async def test_starting_again_replaces_a_login_that_is_waiting(tmp_path: Path) -> None:
    logins = Logins(pin="123456")
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        await store(rig)
        await post(rig, "login/start")
        await post(rig, "login/start")
        assert len(logins.made) == 2
        assert (await post(rig, "login/pin", {"pin": "123456"})).json()["state"] == "logged_in"
        assert logins.made[0].pins_seen == [] and logins.made[1].pins_seen == ["123456"]


# --- the engine and the login ------------------------------------------------------------------


async def test_the_login_and_logout_need_the_engine_stopped(tmp_path: Path) -> None:
    logins = Logins()
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        await store(rig)
        await post(rig, "login/start")
        await rig.client.post(f"{API}/engine/start")
        for path in ("login/start", "logout"):
            refused = await post(rig, path)
            assert (
                refused.status_code == 409 and refused.json()["error"]["code"] == "engine_running"
            )
        assert (await status(rig))["engine_running"] is True
        await rig.client.post(f"{API}/engine/stop")
        assert (await post(rig, "logout")).status_code == 200


async def test_the_engine_is_built_with_the_stored_session(tmp_path: Path) -> None:
    seen: list[Settings] = []
    parts: list[FakeParts] = []
    inner = fake_builder(parts)

    def spy(settings: Settings, bus: EventBus, tasks: TaskSupervisor) -> Engine:
        seen.append(settings)
        return inner(settings, bus, tasks)

    async with running_api(tmp_path, secret_key=KEY, quotex_login=Logins(), builder=spy) as rig:
        await store(rig)
        before = (await rig.client.get(f"{API}/engine")).json()
        item = next(i for i in before["logins"] if i["label"] == "Quotex login")
        assert item["source"] == "missing" and item["required"] is False
        assert "Quotex login" not in before["missing_logins"]  # it can start without it

        await post(rig, "login/start")
        after = (await rig.client.get(f"{API}/engine")).json()
        item = next(i for i in after["logins"] if i["label"] == "Quotex login")
        assert item["source"] == "dashboard" and item["present"] is True

        await rig.client.post(f"{API}/engine/start")
        assert seen[-1].quotex_session is not None
        assert seen[-1].quotex_session.get_secret_value() == SESSION


async def test_logging_out_removes_the_stored_session(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, quotex_login=Logins()) as rig:
        await store(rig)
        await post(rig, "login/start")
        out = await post(rig, "logout")
        assert out.status_code == 200 and out.json()["state"] == "logged_out"
        assert stored(rig, "quotex_session") is None
        assert (await post(rig, "logout")).status_code == 200  # harmless when logged out
        # the email and password are kept: logging in again needs nothing typed
        assert (await status(rig))["configured"] is True


async def test_a_stored_session_that_cannot_be_read_is_not_a_login(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, quotex_login=Logins()) as rig:
        await store(rig)
        await post(rig, "login/start")
    async with running_api(tmp_path, secret_key=generate_key(), quotex_login=Logins()) as rig:
        item = next(
            i
            for i in (await rig.client.get(f"{API}/engine")).json()["logins"]
            if i["label"] == "Quotex login"
        )
        assert item["source"] == "unreadable" and item["present"] is False


# --- secrets stay secret -----------------------------------------------------------------------


async def test_no_password_pin_or_session_reaches_the_database_the_log_or_an_answer(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    logins = Logins(pin="123456")
    async with running_api(tmp_path, secret_key=KEY, quotex_login=logins) as rig:
        await store(rig)
        texts = [
            (await post(rig, "login/start")).text,
            (await post(rig, "login/pin", {"pin": "123456"})).text,
            (await rig.client.get(f"{API}/quotex/login")).text,
            (await rig.client.get(f"{API}/engine")).text,
            (await rig.client.get(f"{API}/secrets")).text,
        ]
        db_path = rig.settings.database_path
        data_dir = rig.settings.data_dir
    raw = b"".join(p.read_bytes() for p in (db_path, Path(f"{db_path}-wal")) if p.exists())
    logs = capfd.readouterr()
    for secret in (PASSWORD, "tok-123-secret", "123456", EMAIL):
        assert secret.encode() not in raw, secret
        for text in (*texts, logs.out, logs.err):
            assert secret not in text, secret
    # and nothing about the login was written to the data folder either
    for path in data_dir.rglob("*"):
        if path.is_file() and path != db_path and not path.name.startswith("quotex.db"):
            assert b"tok-123-secret" not in path.read_bytes(), path


async def test_every_quotex_login_route_needs_a_session(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, logged_in=False) as rig:
        for method, path in (
            ("GET", "/quotex/login"),
            ("POST", "/quotex/login/start"),
            ("POST", "/quotex/login/pin"),
            ("POST", "/quotex/login/cancel"),
            ("POST", "/quotex/logout"),
        ):
            response = await rig.client.request(method, f"{API}{path}", json={})
            assert response.status_code == 401, (method, path)
