"""The owner's login: first-run setup, login, sessions, the password, and that nothing is open."""

from __future__ import annotations

import re
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from app.auth.service import SESSION_COOKIE
from app.db.models import AuthSession
from app.main import create_app
from tests.api_support import (
    BASE_URL,
    OWNER_NAME,
    OWNER_PASSWORD,
    ApiRig,
    running_api,
    serve,
    settings_for,
)

API = "/api/v1"
NEW_PASSWORD = "a different long password"
SETUP_CODE = re.compile(r"^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$")


def setup_code(rig: ApiRig) -> str:
    code: str | None = rig.app.state.auth._setup_code
    assert code is not None
    return code


def another_browser(rig: ApiRig) -> httpx.AsyncClient:
    """A second client with its own (empty) cookie jar, talking to the same application."""
    transport = httpx.ASGITransport(app=rig.app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url=BASE_URL)


async def log_in(client: httpx.AsyncClient, password: str = OWNER_PASSWORD) -> httpx.Response:
    return await client.post(
        f"{API}/auth/login", json={"username": OWNER_NAME, "password": password}
    )


# --- nothing is open -------------------------------------------------------------------------

PUBLIC = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/auth/state"),
    ("POST", "/api/v1/auth/setup"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
}


async def test_every_route_but_the_public_ones_refuses_a_visitor_without_a_session(
    tmp_path: Path,
) -> None:
    """Adding a route without protecting it fails here, not in production."""
    async with running_api(tmp_path, logged_in=False) as rig:
        checked = 0
        for template, methods in rig.app.openapi()["paths"].items():
            path = re.sub(r"\{[^}]+\}", "1", template)
            for method in (m.upper() for m in methods):
                if (method, template) in PUBLIC:
                    continue
                response = await rig.client.request(method, path, json={})
                assert response.status_code == 401, (method, template, response.text)
                assert response.json()["error"]["code"] == "not_authenticated"
                checked += 1
        assert checked >= 30  # the whole API was walked, not an empty list


async def test_a_garbage_or_unknown_cookie_is_no_session(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        for value in ("", "nonsense", "A" * 5000, "../../etc/passwd"):
            response = await rig.client.get(
                f"{API}/status", headers={"Cookie": f"{SESSION_COOKIE}={value}"}
            )
            assert response.status_code == 401


async def test_the_health_check_needs_no_login(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        assert (await rig.client.get(f"{API}/health")).status_code == 200


async def test_the_websocket_needs_a_session(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig, serve(rig.app) as address:
        with pytest.raises(InvalidStatus) as refused:
            async with connect(f"ws://{address}/ws"):
                pass
        assert refused.value.response.status_code == 403
        with pytest.raises(InvalidStatus) as forged:
            async with connect(
                f"ws://{address}/ws", additional_headers={"Cookie": f"{SESSION_COOKIE}=forged"}
            ):
                pass
        assert forged.value.response.status_code == 403
        async with connect(f"ws://{address}/ws", additional_headers=rig.ws_headers()) as ws:
            assert '"snapshot"' in await ws.recv()


async def test_logging_in_from_another_site_is_refused(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        await rig.app.state.auth.set_owner(username=OWNER_NAME, password=OWNER_PASSWORD)
        response = await rig.client.post(
            f"{API}/auth/login",
            json={"username": OWNER_NAME, "password": OWNER_PASSWORD},
            headers={"Origin": "http://evil.example"},
        )
        assert response.status_code == 403
        assert "set-cookie" not in response.headers


# --- first run ---------------------------------------------------------------------------------


async def test_a_new_installation_asks_for_the_setup_code_and_then_closes_for_good(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        state = (await rig.client.get(f"{API}/auth/state")).json()
        assert state == {"setup_required": True, "authenticated": False, "user": None}
        assert SETUP_CODE.match(setup_code(rig))

        body = {"username": "joseph", "password": "a long enough password"}
        wrong = await rig.client.post(f"{API}/auth/setup", json={**body, "setup_code": "NOPE"})
        assert wrong.status_code == 403
        assert wrong.json()["error"]["code"] == "wrong_setup_code"
        assert "set-cookie" not in wrong.headers
        assert (await rig.client.get(f"{API}/status")).status_code == 401

        # typed by a person: capitals, small letters and spaces around it do not matter
        right = await rig.client.post(
            f"{API}/auth/setup", json={**body, "setup_code": f"  {setup_code(rig).lower()} "}
        )
        assert right.status_code == 201, right.text
        assert right.json() == {"username": "joseph", "role": "admin"}
        assert (await rig.client.get(f"{API}/status")).status_code == 200  # logged in at once

        state = (await rig.client.get(f"{API}/auth/state")).json()
        assert state["setup_required"] is False and state["authenticated"] is True

        again = await another_browser(rig).post(
            f"{API}/auth/setup",
            json={"setup_code": "ABCD-EFGH-JKMN", "username": "intruder", "password": "x" * 20},
        )
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "setup_closed"


async def test_the_setup_cookie_cannot_be_read_by_scripts_or_sent_from_other_sites(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        response = await rig.client.post(
            f"{API}/auth/setup",
            json={
                "setup_code": setup_code(rig),
                "username": "joseph",
                "password": "a long enough password",
            },
        )
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{SESSION_COOKIE}=")
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie or "samesite=strict" in cookie.lower()
        assert "Path=/" in cookie
        assert "Max-Age=2592000" in cookie  # 30 days


async def test_too_many_wrong_setup_codes_lock_the_setup_for_a_while(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        body = {"username": "joseph", "password": "a long enough password"}
        codes = [
            (await rig.client.post(f"{API}/auth/setup", json={**body, "setup_code": f"BAD{i}"}))
            for i in range(6)
        ]
        assert [r.status_code for r in codes] == [403] * 5 + [429]
        # even the right code is refused during the lock
        locked = await rig.client.post(
            f"{API}/auth/setup", json={**body, "setup_code": setup_code(rig)}
        )
        assert locked.status_code == 429


@pytest.mark.parametrize(
    ("username", "password", "fragment"),
    [
        ("a", "a long enough password", "username"),
        ("has space", "a long enough password", "username"),
        ("joseph", "short", "at least 10"),
        ("joseph", "joseph", "at least 10"),
    ],
)
async def test_setup_refuses_a_bad_username_or_password_and_says_why(
    tmp_path: Path, username: str, password: str, fragment: str
) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        response = await rig.client.post(
            f"{API}/auth/setup",
            json={"setup_code": setup_code(rig), "username": username, "password": password},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_account"
        assert fragment in response.json()["error"]["message"]
        assert rig.app.state.auth.setup_required  # a refused attempt does not use up the setup


async def test_an_account_made_by_the_command_closes_the_setup(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        await rig.app.state.auth.set_owner(username=OWNER_NAME, password=OWNER_PASSWORD)
        state = (await rig.client.get(f"{API}/auth/state")).json()
        assert state["setup_required"] is False


# --- logging in --------------------------------------------------------------------------------


async def test_login_and_logout(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        await rig.app.state.auth.set_owner(username=OWNER_NAME, password=OWNER_PASSWORD)
        assert (await rig.client.get(f"{API}/status")).status_code == 401

        response = await log_in(rig.client)
        assert response.status_code == 200
        assert response.json() == {"username": OWNER_NAME, "role": "admin"}
        assert (await rig.client.get(f"{API}/status")).status_code == 200
        state = (await rig.client.get(f"{API}/auth/state")).json()
        assert state["authenticated"] is True and state["user"]["username"] == OWNER_NAME

        assert (await rig.client.post(f"{API}/auth/logout")).status_code == 204
        assert (await rig.client.get(f"{API}/status")).status_code == 401
        assert (await rig.client.post(f"{API}/auth/logout")).status_code == 204  # harmless twice


async def test_logging_out_ends_that_session_on_the_server_not_only_in_the_browser(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        stolen = rig.client.cookies[SESSION_COOKIE]
        await rig.client.post(f"{API}/auth/logout")
        replay = await another_browser(rig).get(
            f"{API}/status", headers={"Cookie": f"{SESSION_COOKIE}={stolen}"}
        )
        assert replay.status_code == 401


async def test_a_wrong_password_and_an_unknown_user_look_exactly_alike(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        await rig.app.state.auth.set_owner(username=OWNER_NAME, password=OWNER_PASSWORD)
        wrong = await log_in(rig.client, "not the password")
        unknown = await rig.client.post(
            f"{API}/auth/login", json={"username": "nobody", "password": "not the password"}
        )
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()
        assert wrong.json()["error"]["code"] == "invalid_login"
        assert "set-cookie" not in wrong.headers and "set-cookie" not in unknown.headers


async def test_repeated_failures_lock_the_name_even_for_the_right_password(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, logged_in=False, api_command_burst=1000) as rig:
        await rig.app.state.auth.set_owner(username=OWNER_NAME, password=OWNER_PASSWORD)
        codes = [(await log_in(rig.client, f"wrong password {i}")).status_code for i in range(6)]
        assert codes == [401] * 5 + [429]
        right = await log_in(rig.client)
        assert right.status_code == 429
        assert right.json()["error"]["code"] == "too_many_attempts"
        assert "minute" in right.json()["error"]["message"]
        assert "set-cookie" not in right.headers


async def test_one_success_resets_the_count(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False, api_command_burst=1000) as rig:
        await rig.app.state.auth.set_owner(username=OWNER_NAME, password=OWNER_PASSWORD)
        for _ in range(4):
            assert (await log_in(rig.client, "wrong password")).status_code == 401
        assert (await log_in(rig.client)).status_code == 200
        for _ in range(4):
            assert (await log_in(rig.client, "wrong password")).status_code == 401
        assert (await log_in(rig.client)).status_code == 200  # never reached five in a row


async def test_login_input_is_bounded(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        response = await rig.client.post(
            f"{API}/auth/login", json={"username": "x", "password": "p" * 5000}
        )
        assert response.status_code == 422  # never reaches the (costly) hashing
        missing = await rig.client.post(f"{API}/auth/login", json={"username": "x"})
        assert missing.status_code == 422


# --- sessions end ------------------------------------------------------------------------------


async def expire(rig: ApiRig, **changes: Any) -> None:
    async with rig.app.state.session_factory() as session, session.begin():
        await session.execute(update(AuthSession).values(**changes))


async def test_a_session_ends_after_its_lifetime(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        assert (await rig.client.get(f"{API}/status")).status_code == 200
        await expire(rig, expires_at=rig.app.state.auth._clock.now() - timedelta(seconds=1))
        response = await rig.client.get(f"{API}/status")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"


async def test_a_session_ends_after_a_week_of_not_being_used(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        now = rig.app.state.auth._clock.now()
        await expire(rig, last_seen_at=now - timedelta(days=7, minutes=1))
        assert (await rig.client.get(f"{API}/status")).status_code == 401
        # and the dead session was removed, not just ignored
        async with rig.app.state.session_factory() as session:
            assert (await session.scalars(select(AuthSession))).all() == []


async def test_using_a_session_keeps_it_alive_but_is_not_written_every_time(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        now = rig.app.state.auth._clock.now()
        await expire(rig, last_seen_at=now - timedelta(days=3))
        assert (await rig.client.get(f"{API}/status")).status_code == 200
        async with rig.app.state.session_factory() as session:
            seen = (await session.scalars(select(AuthSession))).one()
        assert now - seen.last_seen_at < timedelta(minutes=1)  # touched


# --- the password ------------------------------------------------------------------------------


async def test_changing_the_password_logs_every_other_browser_out(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        phone = another_browser(rig)
        assert (await log_in(phone)).status_code == 200
        assert (await phone.get(f"{API}/status")).status_code == 200

        response = await rig.client.post(
            f"{API}/auth/password",
            json={"current_password": OWNER_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 204
        assert (await rig.client.get(f"{API}/status")).status_code == 200  # this one stays
        assert (await phone.get(f"{API}/status")).status_code == 401  # the other is out

        assert (await log_in(another_browser(rig))).status_code == 401  # old password is dead
        assert (await log_in(another_browser(rig), NEW_PASSWORD)).status_code == 200


async def test_the_password_change_checks_the_current_password_and_the_new_one(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        wrong = await rig.client.post(
            f"{API}/auth/password",
            json={"current_password": "not it at all", "new_password": NEW_PASSWORD},
        )
        assert wrong.status_code == 401
        assert wrong.json()["error"]["code"] == "invalid_login"
        weak = await rig.client.post(
            f"{API}/auth/password",
            json={"current_password": OWNER_PASSWORD, "new_password": "short"},
        )
        assert weak.status_code == 422 and "at least 10" in weak.json()["error"]["message"]
        assert (await log_in(another_browser(rig))).status_code == 200  # nothing changed


async def test_changing_the_password_needs_a_session(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        response = await rig.client.post(
            f"{API}/auth/password",
            json={"current_password": OWNER_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 401


async def test_guessing_the_current_password_is_throttled_too(tmp_path: Path) -> None:
    async with running_api(tmp_path, api_command_burst=1000) as rig:
        codes = [
            (
                await rig.client.post(
                    f"{API}/auth/password",
                    json={"current_password": f"guess number {i}", "new_password": NEW_PASSWORD},
                )
            ).status_code
            for i in range(6)
        ]
        assert codes == [401] * 5 + [429]


async def test_the_command_resets_the_password_and_ends_every_session(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        name, created = await rig.app.state.auth.set_owner(username=None, password=NEW_PASSWORD)
        assert (name, created) == (OWNER_NAME, False)
        assert (await rig.client.get(f"{API}/status")).status_code == 401
        assert (await log_in(rig.client)).status_code == 401
        assert (await log_in(rig.client, NEW_PASSWORD)).status_code == 200


def database_bytes(db_path: Path) -> bytes:
    """Everything on disk that holds the database, the write-ahead log included."""
    files = (db_path, Path(f"{db_path}-wal"))
    return b"".join(path.read_bytes() for path in files if path.exists())


# --- secrets stay secret -----------------------------------------------------------------------


async def test_no_password_token_or_hash_reaches_the_database_the_logs_or_a_response(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        bodies: list[str] = []
        setup = await rig.client.post(
            f"{API}/auth/setup",
            json={
                "setup_code": setup_code(rig),
                "username": "joseph",
                "password": "my very private password",
            },
        )
        bodies.append(setup.text)
        token = rig.client.cookies[SESSION_COOKIE]
        await rig.client.post(
            f"{API}/auth/login", json={"username": "joseph", "password": "wrong password here"}
        )
        for path in ("auth/state", "status", "health"):
            bodies.append((await rig.client.get(f"{API}/{path}")).text)
        await rig.client.post(
            f"{API}/auth/password",
            json={"current_password": "my very private password", "new_password": NEW_PASSWORD},
        )
        db_path = rig.settings.database_path

    with sqlite3.connect(db_path) as connection:
        stored = connection.execute("SELECT password_hash FROM users").fetchone()[0]
        token_hashes = [
            row[0] for row in connection.execute("SELECT token_hash FROM auth_sessions")
        ]
    raw = database_bytes(db_path)
    logged = capfd.readouterr()
    everything = "".join(bodies) + logged.out + logged.err
    for secret in (
        "my very private password",
        "wrong password here",
        NEW_PASSWORD,
        token,
        stored,
    ):
        assert secret not in everything, secret
    for secret in (b"my very private password", NEW_PASSWORD.encode(), token.encode()):
        assert secret not in raw
    assert stored.startswith("scrypt$")
    assert token not in token_hashes and len(token_hashes[0]) == 64  # only a SHA-256 is kept


async def test_the_app_survives_a_restart_with_the_owner_still_logged_in(tmp_path: Path) -> None:
    """Sessions are in the database, not in memory."""
    async with running_api(tmp_path) as rig:
        token = rig.client.cookies[SESSION_COOKIE]
    app = create_app(settings_for(tmp_path))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client,
    ):
        assert app.state.auth.setup_required is False  # an account exists: no setup code
        response = await client.get(
            f"{API}/status", headers={"Cookie": f"{SESSION_COOKIE}={token}"}
        )
        assert response.status_code == 200
