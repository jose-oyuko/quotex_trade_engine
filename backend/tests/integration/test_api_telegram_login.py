"""Logging in to Telegram from the dashboard, step by step, on a fake Telegram."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.engine.engine import Engine
from app.events.bus import EventBus
from app.telegram.fake import FakeTelegramSource
from app.telegram.source import FloodWaitLoginError, TelegramError
from app.vault.crypto import generate_key
from tests.api_support import ApiRig, FakeParts, fake_builder, running_api
from tests.signal_support import ManualClock

API = "/api/v1"
KEY = generate_key()
PHONE = "+254712345678"
SESSION_TEXT = "fake-session-for-+254712345678"


class Fakes:
    """The Telegram connections the login makes, one per call to the factory."""

    def __init__(self, *, two_step: str | None = None) -> None:
        self.sources: list[FakeTelegramSource] = []
        self.two_step = two_step
        self.calls: list[tuple[int, str, str | None]] = []

    def __call__(self, api_id: int, api_hash: str, session: str | None) -> FakeTelegramSource:
        self.calls.append((api_id, api_hash, session))
        source = FakeTelegramSource(
            ManualClock(),
            authorized=bool(session),
            login_code="12345",
            two_step_password=self.two_step,
            session=session,
        )
        self.sources.append(source)
        return source

    @property
    def last(self) -> FakeTelegramSource:
        return self.sources[-1]


async def store_api(rig: ApiRig, api_id: str = "123456", api_hash: str = "abcdef0123") -> None:
    assert (
        await rig.client.put(f"{API}/secrets/telegram_api_id", json={"value": api_id})
    ).is_success
    assert (
        await rig.client.put(f"{API}/secrets/telegram_api_hash", json={"value": api_hash})
    ).is_success


async def post(rig: ApiRig, path: str, body: dict[str, Any] | None = None) -> Any:
    return await rig.client.post(f"{API}/telegram/{path}", json=body or {})


async def status(rig: ApiRig) -> dict[str, Any]:
    body: dict[str, Any] = (await rig.client.get(f"{API}/telegram/login")).json()
    return body


def stored(rig: ApiRig, name: str) -> str | None:
    with sqlite3.connect(rig.settings.database_path) as db:
        row = db.execute("SELECT ciphertext FROM secrets WHERE name = ?", (name,)).fetchone()
    return None if row is None else str(row[0])


# --- the happy path ----------------------------------------------------------------------------


async def test_a_new_installation_is_logged_out_and_needs_the_api_credentials_first(
    tmp_path: Path,
) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        body = await status(rig)
        assert body["state"] == "logged_out" and body["configured"] is False
        refused = await post(rig, "login/start", {"phone": PHONE})
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "telegram_not_configured"
        assert "my.telegram.org" in refused.json()["error"]["message"]
        assert fakes.sources == []  # nothing was opened

        await store_api(rig)
        assert (await status(rig))["configured"] is True


async def test_the_api_credentials_in_env_are_enough_to_begin(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(
        tmp_path,
        secret_key=KEY,
        login_source=fakes,
        telegram_api_id=99,
        telegram_api_hash="envhash",
    ) as rig:
        assert (await status(rig))["configured"] is True
        assert (await post(rig, "login/start", {"phone": PHONE})).status_code == 200
        assert fakes.calls == [(99, "envhash", None)]


async def test_logging_in_with_a_code_stores_the_session_encrypted(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        started = await post(rig, "login/start", {"phone": "+254 712 345 678"})
        assert started.status_code == 200
        body = started.json()
        assert body["state"] == "code_sent" and body["delivery"] == "to your Telegram app"
        assert body["phone_hint"] == "+254••••••678" and PHONE not in started.text
        assert body["resends_left"] == 2
        assert fakes.calls == [(123456, "abcdef0123", None)]  # the stored id and hash were used

        done = await post(rig, "login/code", {"code": " 12345 "})
        assert done.status_code == 200 and done.json()["state"] == "logged_in"
        assert done.json()["phone_hint"] == "+254••••••678"
        assert fakes.last.disconnect_calls >= 1  # the login connection was closed

        sealed = stored(rig, "telegram_session")
        assert sealed is not None and sealed.startswith("v1.") and SESSION_TEXT not in sealed
        phone_sealed = stored(rig, "telegram_phone")
        assert phone_sealed is not None and PHONE not in phone_sealed
        assert (await rig.app.state.vault.get("telegram_session")) == SESSION_TEXT
        assert (await status(rig))["state"] == "logged_in"


async def test_the_session_and_phone_are_never_listed_or_settable_through_the_secrets_api(
    tmp_path: Path,
) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        await post(rig, "login/code", {"code": "12345"})
        listed = (await rig.client.get(f"{API}/secrets")).json()
        names = {i["name"] for i in listed["items"]}
        assert names == {
            "quotex_email",
            "quotex_password",
            "telegram_api_id",
            "telegram_api_hash",
        }
        for name in ("telegram_session", "telegram_phone"):
            put = await rig.client.put(f"{API}/secrets/{name}", json={"value": "x"})
            assert put.status_code == 404 and put.json()["error"]["code"] == "unknown_secret"
            assert (await rig.client.delete(f"{API}/secrets/{name}")).status_code == 404
        assert stored(rig, "telegram_session") is not None  # the attempts changed nothing


async def test_nothing_secret_reaches_the_database_the_log_or_an_answer(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    fakes = Fakes(two_step="my two step secret")
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig, api_hash="the-api-hash-value")
        texts = [
            (await post(rig, "login/start", {"phone": PHONE})).text,
            (await post(rig, "login/code", {"code": "12345"})).text,
            (await post(rig, "login/password", {"password": "my two step secret"})).text,
            (await rig.client.get(f"{API}/telegram/login")).text,
            (await rig.client.get(f"{API}/engine")).text,
            (await rig.client.get(f"{API}/secrets")).text,
        ]
        db_path = rig.settings.database_path
    raw = b"".join(p.read_bytes() for p in (db_path, Path(f"{db_path}-wal")) if p.exists())
    logs = capfd.readouterr()
    for secret in (SESSION_TEXT, PHONE, "my two step secret", "the-api-hash-value", "12345"):
        assert secret.encode() not in raw, secret
        for text in (*texts, logs.out, logs.err):
            assert secret not in text, secret


# --- the second step ---------------------------------------------------------------------------


async def test_a_wrong_code_can_be_retyped_without_starting_over(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        wrong = await post(rig, "login/code", {"code": "00000"})
        assert wrong.status_code == 422
        assert wrong.json()["error"]["code"] == "telegram_code_invalid"
        assert (await status(rig))["state"] == "code_sent"  # still waiting for the right one
        assert (await post(rig, "login/code", {"code": "12345"})).json()["state"] == "logged_in"
        assert len(fakes.sources) == 1  # one conversation with Telegram throughout


async def test_an_expired_code_ends_the_login_and_says_to_start_again(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        late = await post(rig, "login/code", {"code": "expired"})
        assert late.status_code == 409 and late.json()["error"]["code"] == "telegram_code_expired"
        assert "Start again" in late.json()["error"]["message"]
        assert (await status(rig))["state"] == "logged_out"
        assert fakes.last.disconnect_calls >= 1
        assert stored(rig, "telegram_session") is None


async def test_the_code_can_be_sent_another_way_a_limited_number_of_times(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        fakes.last.max_resends = 5  # Telegram would allow more; our own limit is two
        first = await post(rig, "login/resend")
        assert first.status_code == 200 and first.json()["delivery"] == "by SMS"
        assert first.json()["resends_left"] == 1
        assert (await post(rig, "login/resend")).json()["resends_left"] == 0
        third = await post(rig, "login/resend")
        assert (
            third.status_code == 422 and third.json()["error"]["code"] == "telegram_login_refused"
        )


async def test_telegram_having_no_other_way_to_send_the_code_is_explained(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        fakes.last.max_resends = 0
        refused = await post(rig, "login/resend")
        assert refused.status_code == 422
        assert "no other way" in refused.json()["error"]["message"]
        assert (await status(rig))["state"] == "code_sent"


# --- two-step verification ---------------------------------------------------------------------


async def test_an_account_with_two_step_verification_asks_for_the_password_next(
    tmp_path: Path,
) -> None:
    fakes = Fakes(two_step="correct horse")
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        after_code = await post(rig, "login/code", {"code": "12345"})
        assert after_code.status_code == 200 and after_code.json()["state"] == "password_needed"
        assert stored(rig, "telegram_session") is None  # not logged in yet

        wrong = await post(rig, "login/password", {"password": "nope"})
        assert wrong.status_code == 422
        assert wrong.json()["error"]["code"] == "telegram_password_invalid"
        assert (await status(rig))["state"] == "password_needed"

        done = await post(rig, "login/password", {"password": "correct horse"})
        assert done.json()["state"] == "logged_in"
        assert stored(rig, "telegram_session") is not None


async def test_steps_out_of_order_are_refused(tmp_path: Path) -> None:
    fakes = Fakes(two_step="pw")
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        for path, body in (
            ("login/code", {"code": "12345"}),
            ("login/password", {"password": "pw"}),
            ("login/resend", None),
        ):
            response = await post(rig, path, body)
            assert response.status_code == 409, path
            assert response.json()["error"]["code"] == "telegram_login_step"
        await post(rig, "login/start", {"phone": PHONE})
        assert (await post(rig, "login/password", {"password": "pw"})).status_code == 409
        await post(rig, "login/code", {"code": "12345"})  # now at the password step
        assert (await post(rig, "login/code", {"code": "12345"})).status_code == 409
        assert (await post(rig, "login/resend")).status_code == 409


# --- surviving a reload, expiring, cancelling --------------------------------------------------


async def test_a_half_made_login_is_still_there_after_a_page_reload_even_in_another_browser(
    tmp_path: Path,
) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        reloaded = await status(rig)  # what a page reload asks
        assert reloaded["state"] == "code_sent" and reloaded["delivery"] == "to your Telegram app"
        assert reloaded["phone_hint"] == "+254••••••678"
        # and it can be finished from there
        assert (await post(rig, "login/code", {"code": "12345"})).json()["state"] == "logged_in"


async def test_a_login_left_for_ten_minutes_is_forgotten(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        rig.app.state.telegram_login._attempt.started -= timedelta(minutes=11)
        assert (await status(rig))["state"] == "logged_out"
        assert fakes.last.disconnect_calls >= 1
        late = await post(rig, "login/code", {"code": "12345"})
        assert late.status_code == 409 and late.json()["error"]["code"] == "telegram_login_step"


async def test_cancelling_drops_the_login_and_closes_the_connection(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        cancelled = await post(rig, "login/cancel")
        assert cancelled.json()["state"] == "logged_out"
        assert fakes.last.disconnect_calls >= 1
        assert (await post(rig, "login/cancel")).status_code == 200  # harmless twice


async def test_starting_again_replaces_the_earlier_attempt(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        await post(rig, "login/start", {"phone": "+254700000001"})
        assert len(fakes.sources) == 2 and fakes.sources[0].disconnect_calls >= 1
        assert (await status(rig))["phone_hint"] == "+254••••••001"


# --- when Telegram says no ---------------------------------------------------------------------


@pytest.mark.parametrize("phone", ["0712345678", "254712345678", "+1", "not a phone", "+254 7x2"])
async def test_a_phone_number_in_the_wrong_form_is_explained_before_telegram_is_asked(
    tmp_path: Path, phone: str
) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        response = await post(rig, "login/start", {"phone": phone})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "telegram_login_refused"
        assert "international" in response.json()["error"]["message"]
        assert fakes.sources == []


async def test_a_flood_wait_says_how_long_to_wait_and_keeps_the_state(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        fakes.last.scripted["sign_in"] = [FloodWaitLoginError(300)]
        waiting = await post(rig, "login/code", {"code": "12345"})
        assert waiting.status_code == 429 and waiting.json()["error"]["code"] == "telegram_wait"
        assert "5 minute" in waiting.json()["error"]["message"]
        assert (await status(rig))["state"] == "code_sent"  # the right code still works later


async def test_a_flood_wait_when_asking_for_the_code_leaves_nothing_open(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)

        class Early(Fakes):
            def __call__(self, api_id: int, api_hash: str, session: str | None) -> Any:
                source = super().__call__(api_id, api_hash, session)
                source.scripted["request_code"] = [FloodWaitLoginError(90)]
                return source

        rig.app.state.telegram_login._make_source = Early()
        response = await post(rig, "login/start", {"phone": PHONE})
        assert response.status_code == 429 and "2 minute" in response.json()["error"]["message"]
        assert (await status(rig))["state"] == "logged_out"


async def test_not_reaching_telegram_is_explained_not_a_crash(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        rig.app.state.telegram_login._make_source = _unreachable
        response = await post(rig, "login/start", {"phone": PHONE})
        assert response.status_code == 422
        assert "Could not reach Telegram" in response.json()["error"]["message"]
        assert (await status(rig))["state"] == "logged_out"


def _unreachable(api_id: int, api_hash: str, session: str | None) -> FakeTelegramSource:
    source = FakeTelegramSource(ManualClock())
    source.connect_failures = 1
    return source


async def test_an_unexpected_error_from_telegram_does_not_leak_into_the_answer(
    tmp_path: Path,
) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        fakes.last.scripted["sign_in"] = [RuntimeError("secret-internal-detail 12345")]
        response = await post(rig, "login/code", {"code": "12345"})
        assert response.status_code == 422
        assert "secret-internal-detail" not in response.text
        assert TelegramError  # (the type exists; unknown errors are reported generically)


# --- the engine and the login ------------------------------------------------------------------


async def test_the_login_and_the_logout_need_the_engine_stopped(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        await post(rig, "login/code", {"code": "12345"})
        await rig.client.post(f"{API}/engine/start")
        assert (await status(rig))["engine_running"] is True

        for path, body in (("login/start", {"phone": PHONE}), ("logout", None)):
            refused = await post(rig, path, body)
            assert (
                refused.status_code == 409 and refused.json()["error"]["code"] == "engine_running"
            )
        assert (await status(rig))["state"] == "logged_in"  # nothing was lost

        await rig.client.post(f"{API}/engine/stop")
        assert (await post(rig, "logout")).status_code == 200


async def test_the_engine_is_built_with_the_stored_api_id_and_session(tmp_path: Path) -> None:
    seen: list[Settings] = []
    parts: list[FakeParts] = []
    inner = fake_builder(parts)

    def spy(settings: Settings, bus: EventBus, tasks: TaskSupervisor) -> Engine:
        seen.append(settings)
        return inner(settings, bus, tasks)

    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes, builder=spy) as rig:
        await store_api(rig, api_id="777", api_hash="stored-hash")
        await post(rig, "login/start", {"phone": PHONE})
        await post(rig, "login/code", {"code": "12345"})
        body = (await rig.client.get(f"{API}/engine")).json()
        sources = {i["label"]: i["source"] for i in body["logins"]}
        assert sources["Telegram login"] == "dashboard"
        assert (
            sources["Telegram API id"] == "dashboard"
            and sources["Telegram API hash"] == "dashboard"
        )

        await rig.client.post(f"{API}/engine/start")
        used = seen[-1]
        assert used.telegram_api_id == 777
        assert used.telegram_api_hash is not None
        assert used.telegram_api_hash.get_secret_value() == "stored-hash"
        assert used.telegram_session is not None
        assert used.telegram_session.get_secret_value() == SESSION_TEXT


async def test_without_a_login_the_engine_page_says_so(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, login_source=Fakes()) as rig:
        body = (await rig.client.get(f"{API}/engine")).json()
        assert "Telegram login" in body["missing_logins"]


async def test_a_stored_login_that_cannot_be_read_is_reported_and_stops_the_engine_start(
    tmp_path: Path,
) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        await post(rig, "login/code", {"code": "12345"})
    async with running_api(tmp_path, secret_key=generate_key(), login_source=fakes) as rig:
        body = await status(rig)
        assert body["state"] == "logged_out" and "cannot be read" in body["problem"]
        start = await rig.client.post(f"{API}/engine/start")
        assert start.status_code == 409
        assert "stored" in start.json()["error"]["message"]


# --- logging out -------------------------------------------------------------------------------


async def test_logging_out_removes_the_session_and_ends_it_on_telegram(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        await post(rig, "login/code", {"code": "12345"})
        out = await post(rig, "logout")
        assert out.status_code == 200 and out.json()["state"] == "logged_out"
        assert out.json()["phone_hint"] is None
        assert stored(rig, "telegram_session") is None and stored(rig, "telegram_phone") is None
        assert fakes.last.logged_out is True  # Telegram was told, with the saved session
        assert fakes.calls[-1][2] == SESSION_TEXT
        # the API id and hash are kept: logging in again needs only the phone
        assert (await status(rig))["configured"] is True


async def test_logging_out_works_even_if_telegram_cannot_be_reached(tmp_path: Path) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        await store_api(rig)
        await post(rig, "login/start", {"phone": PHONE})
        await post(rig, "login/code", {"code": "12345"})

        def unreachable_logout(api_id: int, api_hash: str, session: str | None) -> Any:
            source = fakes(api_id, api_hash, session)
            source.scripted["log_out"] = [TelegramError("offline")]
            return source

        rig.app.state.telegram_login._make_source = unreachable_logout
        out = await post(rig, "logout")
        assert out.status_code == 200 and out.json()["state"] == "logged_out"
        assert stored(rig, "telegram_session") is None


async def test_logging_out_also_removes_the_file_the_command_line_login_made(
    tmp_path: Path,
) -> None:
    fakes = Fakes()
    async with running_api(tmp_path, secret_key=KEY, login_source=fakes) as rig:
        legacy = rig.settings.data_dir / "telegram.session"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(b"old login")
        body = (await rig.client.get(f"{API}/engine")).json()
        assert {i["label"]: i["source"] for i in body["logins"]}[
            "Telegram login"
        ] == ".session file"
        assert (await status(rig))["state"] == "logged_in"
        await store_api(rig)
        assert (await post(rig, "logout")).json()["state"] == "logged_out"
        assert not legacy.exists()


async def test_logging_out_when_logged_out_is_harmless(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, login_source=Fakes()) as rig:
        out = await post(rig, "logout")
        assert out.status_code == 200 and out.json()["state"] == "logged_out"


# --- access ------------------------------------------------------------------------------------


async def test_every_telegram_login_route_needs_a_session(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, logged_in=False) as rig:
        for method, path in (
            ("GET", "/telegram/login"),
            ("POST", "/telegram/login/start"),
            ("POST", "/telegram/login/resend"),
            ("POST", "/telegram/login/code"),
            ("POST", "/telegram/login/password"),
            ("POST", "/telegram/login/cancel"),
            ("POST", "/telegram/logout"),
        ):
            response = await rig.client.request(method, f"{API}{path}", json={})
            assert response.status_code == 401, (method, path)


@pytest.mark.parametrize("value", ["abc", "0", "-5", "12 34", "1.5", ""])
async def test_the_api_id_must_be_a_number(tmp_path: Path, value: str) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        response = await rig.client.put(f"{API}/secrets/telegram_api_id", json={"value": value})
        assert response.status_code == 422
        assert stored(rig, "telegram_api_id") is None
