"""`GET /brokers`, `PUT /brokers/{broker}` (decision D-81): a broker is switched off and on from the
dashboard, the choice is remembered, and the status and health say so."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.brokers.base import ConnectionState
from app.brokers.errors import LoginRejectedError
from tests.api_support import ApiRig, running_api

API = "/api/v1"


def states(body: dict[str, Any]) -> dict[str, tuple[bool, str]]:
    return {item["broker"]: (item["enabled"], item["state"]) for item in body["items"]}


async def switch(rig: ApiRig, broker: str, enabled: bool) -> Any:
    return await rig.client.put(f"{API}/brokers/{broker}", json={"enabled": enabled})


async def test_quotex_is_switched_off_and_on_while_the_engine_runs(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        adapter = rig.fakes.adapter
        await rig.eventually(lambda: _true(adapter.state is ConnectionState.CONNECTED))
        listed = (await rig.client.get(f"{API}/brokers")).json()
        assert states(listed) == {
            "quotex": (True, "connected"),
            "deriv": (True, "no_login"),
        }

        off = await switch(rig, "quotex", False)
        assert off.status_code == 200
        assert states(off.json())["quotex"] == (False, "off")
        assert adapter.state is ConnectionState.DISCONNECTED
        status = (await rig.client.get(f"{API}/status")).json()
        assert status["brokers_off"] == ["quotex"]
        health = (await rig.client.get(f"{API}/health")).json()
        assert not any("Quotex" in p for p in health["problems"])  # off is not a problem

        on = await switch(rig, "quotex", True)
        assert states(on.json())["quotex"][0] is True
        await rig.eventually(lambda: _true(adapter.state is ConnectionState.CONNECTED))
        assert (await rig.client.get(f"{API}/status")).json()["brokers_off"] == []


async def test_the_switch_is_remembered_when_the_engine_starts_again(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await switch(rig, "quotex", False)
        restarted = await rig.client.post(f"{API}/engine/restart")
        assert restarted.status_code == 200
        new_adapter = rig.parts[-1].adapter
        assert new_adapter.connect_attempts == 0  # the new engine never connected it
        listed = (await rig.client.get(f"{API}/brokers")).json()
        assert states(listed)["quotex"] == (False, "off")


async def test_the_switch_can_be_set_with_the_engine_stopped(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        off = await switch(rig, "deriv", False)
        assert off.status_code == 200
        assert states(off.json())["deriv"] == (False, "off")
        assert states(off.json())["quotex"] == (True, "engine_stopped")


async def test_switching_on_a_broker_without_a_login_is_refused_in_words(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        refused = await switch(rig, "deriv", True)
        assert refused.status_code == 409
        error = refused.json()["error"]
        assert error["code"] == "broker_switch_refused"
        assert "Deriv cannot be switched on: its login is not stored" in error["message"]


async def test_a_pin_request_shows_as_needs_you(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        adapter = rig.fakes.adapter
        await switch(rig, "quotex", False)
        adapter.fail_next_connect(LoginRejectedError("Quotex asked for an email PIN."))
        await switch(rig, "quotex", True)
        await rig.eventually(lambda: _true(adapter.login_problem is not None))

        listed = states((await rig.client.get(f"{API}/brokers")).json())
        assert listed["quotex"] == (True, "needs_you")
        status = (await rig.client.get(f"{API}/status")).json()
        assert status["broker_problems"] == {"quotex": "Quotex asked for an email PIN."}
        health = (await rig.client.get(f"{API}/health")).json()
        assert "Quotex needs you: Quotex asked for an email PIN." in health["problems"]


async def _true(value: bool) -> bool:
    return value
