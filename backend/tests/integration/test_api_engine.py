"""Starting and stopping the engine from the dashboard, and real money behind a password."""

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
from app.quotex.base import ConnectionState
from app.vault.crypto import generate_key
from tests.api_support import (
    OWNER_PASSWORD,
    ApiRig,
    FakeParts,
    fake_builder,
    running_api,
)

API = "/api/v1"
KEY = generate_key()


async def started(rig: ApiRig) -> FakeParts:
    """Start the engine through the API and wait until the fakes behind it are connected."""
    response = await rig.client.post(f"{API}/engine/start")
    assert response.status_code == 200, response.text
    fakes = rig.parts[-1]
    assert await fakes.engine.listener.wait_until_connected(2)

    async def connected() -> bool:
        return fakes.engine.adapter.state is ConnectionState.CONNECTED

    await rig.eventually(connected)
    return fakes


async def engine_state(rig: ApiRig) -> dict[str, Any]:
    body: dict[str, Any] = (await rig.client.get(f"{API}/engine")).json()
    return body


def risk_kinds(rig: ApiRig) -> list[str]:
    with sqlite3.connect(rig.settings.database_path) as db:
        return [row[0] for row in db.execute("SELECT kind FROM risk_events ORDER BY occurred_at")]


# --- start, stop, restart ----------------------------------------------------------------------


async def test_a_new_installation_has_the_engine_stopped_and_says_what_it_would_need(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        body = await engine_state(rig)
        assert body["state"] == "stopped" and body["desired"] is False and body["error"] is None
        assert body["real_trading_allowed"] is False
        assert "Quotex email" in body["missing_logins"]
        assert {i["label"] for i in body["logins"]} == {
            "Quotex email",
            "Quotex password",
            "Telegram API hash",
            "Telegram API id",
            "Telegram login",
            "Quotex login",
        }
        # nothing that needs the engine works yet, and says how to fix it
        refused = await rig.client.post(f"{API}/kill-switch")
        assert refused.status_code == 503
        assert refused.json()["error"]["code"] == "engine_not_running"
        assert "Settings page" in refused.json()["error"]["message"]


async def test_the_engine_can_be_started_stopped_and_started_again_without_restarting_the_app(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        await started(rig)
        body = await engine_state(rig)
        assert body["state"] == "running" and body["desired"] is True
        assert (await rig.client.get(f"{API}/status")).json()["engine"]["running"] is True
        assert (await rig.client.post(f"{API}/kill-switch")).status_code == 200  # it works now

        stopped = await rig.client.post(f"{API}/engine/stop")
        assert stopped.status_code == 200 and stopped.json()["state"] == "stopped"
        assert stopped.json()["desired"] is False
        assert rig.app.state.trading is None
        assert (await rig.client.post(f"{API}/kill-switch")).status_code == 503
        assert (await rig.client.get(f"{API}/status")).json()["engine"]["running"] is False

        await started(rig)
        assert len(rig.parts) == 2  # a fresh engine, not the old one revived
        assert (await engine_state(rig))["state"] == "running"


async def test_starting_a_running_engine_and_stopping_a_stopped_one_change_nothing(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        assert (await rig.client.post(f"{API}/engine/stop")).json()["state"] == "stopped"
        await started(rig)
        again = await rig.client.post(f"{API}/engine/start")
        assert again.status_code == 200 and again.json()["state"] == "running"
        assert len(rig.parts) == 1  # no second engine was built


async def test_restart_builds_a_new_engine_and_leaves_no_task_behind(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await started(rig)
        tasks: TaskSupervisor = rig.app.state.tasks
        await asyncio.sleep(0.1)
        before = tasks.running
        for _ in range(3):
            response = await rig.client.post(f"{API}/engine/restart")
            assert response.status_code == 200 and response.json()["state"] == "running"
            await rig.eventually(_all_connected(rig))
        await asyncio.sleep(0.1)
        assert len(rig.parts) == 4
        assert tasks.running <= before  # nothing piled up over three restarts


def _all_connected(rig: ApiRig) -> Any:
    async def check() -> bool:
        fakes = rig.parts[-1]
        return fakes.engine.adapter.state is ConnectionState.CONNECTED

    return check


async def test_two_requests_at_once_are_not_queued_the_second_is_refused(tmp_path: Path) -> None:
    gate = asyncio.Event()
    parts: list[FakeParts] = []
    inner = fake_builder(parts)

    async def slow(*_: Any) -> None:
        await gate.wait()

    async with running_api(tmp_path, builder=inner) as rig:
        controller = rig.app.state.controller
        original = controller._build

        async def held(real_allowed: bool) -> Engine:
            await slow()
            return await original(real_allowed)

        controller._build = held
        first = asyncio.create_task(rig.client.post(f"{API}/engine/start"))
        await asyncio.sleep(0.05)
        assert (await engine_state(rig))["state"] == "starting"
        second = await rig.client.post(f"{API}/engine/start")
        assert second.status_code == 409 and second.json()["error"]["code"] == "engine_busy"
        assert (await rig.client.post(f"{API}/engine/stop")).status_code == 409
        gate.set()
        assert (await first).status_code == 200


# --- what happens to work in flight ------------------------------------------------------------


async def test_stopping_marks_what_was_in_flight_unknown_at_once(tmp_path: Path) -> None:
    async with running_api(tmp_path, hold_results=True) as rig:
        await rig.client.post(f"{API}/engine/start")
        fakes = rig.parts[-1]
        await rig.eventually(_all_connected(rig))
        await rig.create_group()
        fakes.signal(-1001, "EURUSD CALL 1m")

        async def open_trade() -> bool:
            return bool(fakes.adapter.orders) and bool(fakes.engine.manager.active_chains())

        await rig.eventually(open_trade)
        assert len((await rig.client.get(f"{API}/status")).json()["open_chains"]) == 1

        await rig.client.post(f"{API}/engine/stop")

        async def settled_unknown() -> bool:
            body = (await rig.client.get(f"{API}/status")).json()
            chains = (await rig.client.get(f"{API}/chains")).json()["items"]
            trades = (await rig.client.get(f"{API}/trades")).json()["items"]
            return (
                not body["open_chains"]
                and bool(chains)
                and chains[0]["status"] == "unknown"
                and trades[0]["status"] == "unknown"
            )

        await rig.eventually(settled_unknown)
        assert "restart_unknown" in risk_kinds(rig)


async def test_a_restart_does_not_start_from_what_the_old_engine_left_half_written(
    tmp_path: Path,
) -> None:
    """The new engine reads the database only after everything the old one said is stored: it
    must not see an open chain that was already marked unknown, and must not trade on it."""
    async with running_api(tmp_path, hold_results=True) as rig:
        await rig.client.post(f"{API}/engine/start")
        await rig.eventually(_all_connected(rig))
        await rig.create_group()
        rig.parts[-1].signal(-1001, "EURUSD CALL 1m")
        await rig.eventually(lambda: _orders(rig))
        await rig.client.post(f"{API}/engine/restart")
        await rig.eventually(_all_connected(rig))
        chains = (await rig.client.get(f"{API}/chains")).json()["items"]
        assert [c["status"] for c in chains] == ["unknown"]  # exactly one, ended once
        assert len(rig.parts[-1].adapter.orders) == 0  # the new engine placed nothing


async def _orders(rig: ApiRig) -> bool:
    return bool(rig.parts[-1].adapter.orders)


# --- remembering what the owner decided --------------------------------------------------------


async def test_an_engine_left_running_starts_again_with_the_application(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await started(rig)
    async with running_api(tmp_path) as again:  # the application was restarted
        assert again.app.state.trading is not None
        assert (await engine_state(again))["state"] == "running"


async def test_an_engine_the_owner_stopped_stays_stopped_after_a_restart(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await started(rig)
        await rig.client.post(f"{API}/engine/stop")
    async with running_api(tmp_path) as again:
        assert again.app.state.trading is None
        assert (await engine_state(again))["state"] == "stopped"


async def test_a_new_installation_never_starts_the_engine_by_itself(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        assert rig.app.state.trading is None and rig.parts == []
        body = await engine_state(rig)
        assert body["desired"] is False and body["state"] == "stopped"


async def test_shutting_the_application_down_keeps_the_owners_choice(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await started(rig)
        flags = rig.app.state.controller._flags
    # the engine was stopped by the shutdown, but the choice "running" was not overwritten
    async with running_api(tmp_path) as again:
        assert await again.app.state.controller._flags.desired() is True
    assert flags is not None


# --- when it cannot start ----------------------------------------------------------------------


class Switch:
    """A builder that fails until told to work."""

    def __init__(self) -> None:
        self.parts: list[FakeParts] = []
        self.inner = fake_builder(self.parts)
        self.fail_with: Exception | None = RuntimeError("no luck")
        self.seen: list[Settings] = []

    def __call__(self, settings: Settings, bus: EventBus, tasks: TaskSupervisor) -> Engine:
        self.seen.append(settings)
        if self.fail_with is not None:
            raise self.fail_with
        return self.inner(settings, bus, tasks)


async def test_a_failed_start_says_why_everywhere_and_can_be_tried_again(tmp_path: Path) -> None:
    switch = Switch()
    async with running_api(tmp_path, builder=switch) as rig:
        response = await rig.client.post(f"{API}/engine/start")
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "engine_start_failed" and "no luck" in error["message"]

        body = await engine_state(rig)
        assert body["state"] == "failed" and "no luck" in body["error"]
        assert rig.app.state.trading is None
        status = (await rig.client.get(f"{API}/status")).json()["engine"]
        assert status["state"] == "failed" and "no luck" in status["error"]
        health = (await rig.client.get(f"{API}/health")).json()
        assert health["status"] == "degraded"
        assert any("could not start" in p for p in health["problems"])

        switch.fail_with = None  # the owner fixed it
        again = await rig.client.post(f"{API}/engine/start")
        assert again.status_code == 200 and again.json()["state"] == "running"
        assert again.json()["error"] is None
        health = (await rig.client.get(f"{API}/health")).json()
        assert not any("could not start" in p for p in health["problems"])


async def test_stopping_after_a_failed_start_clears_it(tmp_path: Path) -> None:
    async with running_api(tmp_path, builder=Switch()) as rig:
        await rig.client.post(f"{API}/engine/start")
        stopped = await rig.client.post(f"{API}/engine/stop")
        assert stopped.json()["state"] == "stopped" and stopped.json()["error"] is None


async def test_an_error_message_is_short_and_one_line(tmp_path: Path) -> None:
    switch = Switch()
    switch.fail_with = RuntimeError("line one\nline two " + "x" * 1000)
    async with running_api(tmp_path, builder=switch) as rig:
        response = await rig.client.post(f"{API}/engine/start")
        message = response.json()["error"]["message"]
        assert "\n" not in message and len(message) <= 400


# --- the logins the engine is built with -------------------------------------------------------


async def test_the_engine_uses_the_stored_logins_before_the_env_ones(tmp_path: Path) -> None:
    switch = Switch()
    switch.fail_with = None
    async with running_api(
        tmp_path, builder=switch, secret_key=KEY, quotex_email="env@example.com"
    ) as rig:
        await rig.client.put(f"{API}/secrets/quotex_email", json={"value": "stored@example.com"})
        await rig.client.put(f"{API}/secrets/quotex_password", json={"value": "stored-pw"})
        await rig.client.post(f"{API}/engine/start")
        used = switch.seen[-1]
        assert used.quotex_email is not None
        assert used.quotex_email.get_secret_value() == "stored@example.com"
        assert used.quotex_password is not None
        assert used.quotex_password.get_secret_value() == "stored-pw"
        body = await engine_state(rig)
        sources = {i["label"]: i["source"] for i in body["logins"]}
        assert sources["Quotex email"] == "dashboard"


async def test_the_env_login_is_used_when_nothing_is_stored_and_it_is_said_so(
    tmp_path: Path,
) -> None:
    switch = Switch()
    switch.fail_with = None
    async with running_api(
        tmp_path, builder=switch, secret_key=KEY, quotex_email="env@example.com"
    ) as rig:
        await rig.client.post(f"{API}/engine/start")
        used = switch.seen[-1].quotex_email
        assert used is not None and used.get_secret_value() == "env@example.com"
        sources = {i["label"]: i["source"] for i in (await engine_state(rig))["logins"]}
        assert sources["Quotex email"] == ".env" and sources["Quotex password"] == "missing"


async def test_a_stored_login_that_cannot_be_read_stops_the_start_it_is_not_swapped_for_env(
    tmp_path: Path,
) -> None:
    switch = Switch()
    switch.fail_with = None
    async with running_api(
        tmp_path, builder=switch, secret_key=KEY, quotex_email="env@example.com"
    ) as rig:
        await rig.client.put(f"{API}/secrets/quotex_email", json={"value": "stored@example.com"})
    switch.seen.clear()
    async with running_api(
        tmp_path, builder=switch, secret_key=generate_key(), quotex_email="env@example.com"
    ) as rig:
        response = await rig.client.post(f"{API}/engine/start")
        assert response.status_code == 409
        assert "stored Quotex email cannot be used" in response.json()["error"]["message"]
        assert switch.seen == []  # nothing was built with the wrong login
        sources = {i["label"]: i["source"] for i in (await engine_state(rig))["logins"]}
        assert sources["Quotex email"] == "unreadable"


async def test_no_login_value_appears_in_the_engine_answers(tmp_path: Path) -> None:
    switch = Switch()
    switch.fail_with = None
    async with running_api(tmp_path, builder=switch, secret_key=KEY) as rig:
        await rig.client.put(f"{API}/secrets/quotex_password", json={"value": "very-secret-pw"})
        texts = [
            (await rig.client.post(f"{API}/engine/start")).text,
            (await rig.client.get(f"{API}/engine")).text,
            (await rig.client.get(f"{API}/status")).text,
            (await rig.client.get(f"{API}/health")).text,
        ]
        assert all("very-secret-pw" not in t for t in texts)


# --- real money --------------------------------------------------------------------------------


async def allow_real(rig: ApiRig, allowed: bool = True, password: str = OWNER_PASSWORD) -> Any:
    return await rig.client.put(
        f"{API}/account/real-trading", json={"allowed": allowed, "password": password}
    )


async def test_real_money_is_off_until_the_owner_allows_it_with_the_password(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        fakes = await started(rig)
        no_password = await rig.client.put(f"{API}/account/real-trading", json={"allowed": True})
        assert no_password.status_code == 422
        wrong = await allow_real(rig, password="not the password")
        assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "invalid_login"
        assert (await engine_state(rig))["real_trading_allowed"] is False

        ok = await allow_real(rig)
        assert ok.status_code == 200 and ok.json()["real_trading_allowed"] is True
        assert (await rig.client.get(f"{API}/status")).json()["real_trading_allowed"] is True
        assert fakes.adapter._allow_real is True  # applied to the running engine at once
        await rig.eventually(_has_kind(rig, "real_trading_allowed"))


def _has_kind(rig: ApiRig, kind: str) -> Any:
    async def check() -> bool:
        return kind in risk_kinds(rig)

    return check


async def test_switching_to_the_real_account_needs_the_permission_and_the_password_again(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        await started(rig)
        body = {"account_type": "real", "password": OWNER_PASSWORD}
        refused = await rig.client.put(f"{API}/account", json=body)
        assert refused.status_code == 403  # not allowed yet
        await allow_real(rig)

        missing = await rig.client.put(f"{API}/account", json={"account_type": "real"})
        assert missing.status_code == 422 and missing.json()["error"]["code"] == "password_required"
        wrong = await rig.client.put(
            f"{API}/account", json={"account_type": "real", "password": "nope nope nope"}
        )
        assert wrong.status_code == 401
        assert (await rig.client.get(f"{API}/account")).json()["account_type"] == "demo"

        switched = await rig.client.put(f"{API}/account", json=body)
        assert switched.status_code == 200 and switched.json()["account_type"] == "real"
        await rig.eventually(_has_kind(rig, "switched_to_real"))

        # going back to demo needs no password
        back = await rig.client.put(f"{API}/account", json={"account_type": "demo"})
        assert back.status_code == 200 and back.json()["account_type"] == "demo"


async def test_the_permission_cannot_be_taken_back_while_real_is_in_use(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await started(rig)
        await allow_real(rig)
        await rig.client.put(
            f"{API}/account", json={"account_type": "real", "password": OWNER_PASSWORD}
        )
        refused = await allow_real(rig, allowed=False)
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "real_trading_in_use"
        assert (await engine_state(rig))["real_trading_allowed"] is True

        await rig.client.put(f"{API}/account", json={"account_type": "demo"})
        off = await allow_real(rig, allowed=False)
        assert off.status_code == 200 and off.json()["real_trading_allowed"] is False
        await rig.eventually(_has_kind(rig, "real_trading_disallowed"))


async def test_the_permission_survives_a_restart_but_the_engine_always_starts_on_demo(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        await started(rig)
        await allow_real(rig)
        await rig.client.put(
            f"{API}/account", json={"account_type": "real", "password": OWNER_PASSWORD}
        )
    async with running_api(tmp_path) as again:  # the engine comes back by itself
        assert (await engine_state(again))["real_trading_allowed"] is True
        assert (await again.client.get(f"{API}/account")).json()["account_type"] == "demo"
        assert again.app.state.trading.adapter.account_type.value == "demo"


async def test_allowing_real_money_twice_is_one_entry_in_the_risk_log(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await allow_real(rig)
        await allow_real(rig)
        await rig.eventually(_has_kind(rig, "real_trading_allowed"))
        await asyncio.sleep(0.1)
        assert risk_kinds(rig).count("real_trading_allowed") == 1


async def test_guessing_the_password_for_real_money_is_throttled_with_the_other_attempts(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, api_command_burst=1000) as rig:
        codes = [
            (await allow_real(rig, password=f"guess number {i}")).status_code for i in range(6)
        ]
        assert codes == [401] * 5 + [429]
        assert (await allow_real(rig)).status_code == 429  # even the right one, for now


async def test_the_engine_endpoints_need_a_login(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        for method, path in (
            ("GET", "/engine"),
            ("POST", "/engine/start"),
            ("POST", "/engine/stop"),
            ("POST", "/engine/restart"),
            ("PUT", "/account/real-trading"),
        ):
            response = await rig.client.request(method, f"{API}{path}", json={})
            assert response.status_code == 401, (method, path)


def test_the_password_is_not_part_of_any_answer_model() -> None:
    from app.main import create_app
    from tests.api_support import settings_for

    schemas = create_app(settings_for(Path("."))).openapi()["components"]["schemas"]
    for name in ("EngineOut", "AccountOut", "SnapshotOut"):
        assert "password" not in schemas[name]["properties"], name


@pytest.mark.parametrize("path", ["/engine/start", "/engine/stop", "/engine/restart"])
async def test_the_engine_commands_are_rate_limited_like_other_commands(
    tmp_path: Path, path: str
) -> None:
    async with running_api(tmp_path, api_command_burst=3, api_command_rate_per_s=0.001) as rig:
        codes = [(await rig.client.post(f"{API}{path}")).status_code for _ in range(5)]
        assert codes[-1] == 429
