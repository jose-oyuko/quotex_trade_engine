"""Settings changed in the dashboard instead of `.env`: stored, checked, used at the next start."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.api_support import running_api

API = "/api/v1"


def item(body: dict[str, Any], key: str) -> dict[str, Any]:
    found = next(i for i in body["items"] if i["key"] == key)
    assert isinstance(found, dict)
    return found


async def test_the_settings_are_listed_with_where_each_value_comes_from(tmp_path: Path) -> None:
    async with running_api(tmp_path, quotex_host="qxbroker.example") as rig:
        body = (await rig.client.get(f"{API}/settings")).json()
        assert [i["key"] for i in body["items"]] == ["log_level", "quotex_host", "quotex_time_mode"]
        assert "next start" in body["apply_note"]
        host = item(body, "quotex_host")
        assert host["value"] == "qxbroker.example" and host["source"] == "environment"
        level = item(body, "log_level")
        assert level["value"] == "INFO" and level["source"] == "default"
        assert level["kind"] == "choice" and level["choices"] == [
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
        ]
        assert item(body, "quotex_host")["kind"] == "text"


async def test_a_saved_setting_is_stored_and_wins_over_the_environment(tmp_path: Path) -> None:
    async with running_api(tmp_path, quotex_host="qxbroker.example") as rig:
        response = await rig.client.put(
            f"{API}/settings",
            json={"values": {"quotex_host": "  Quotex.COM ", "log_level": "debug"}},
        )
        assert response.status_code == 200
        host = item(response.json(), "quotex_host")
        assert host["value"] == "quotex.com"  # tidied
        assert host["source"] == "database" and host["default_value"] == "qxbroker.example"
        assert item(response.json(), "log_level")["value"] == "DEBUG"
        assert item(response.json(), "quotex_time_mode")["source"] == "default"  # untouched


async def test_what_was_saved_is_what_the_application_uses_after_a_restart(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        assert rig.app.state.settings.quotex_time_mode == "TIME"
        await rig.client.put(
            f"{API}/settings",
            json={"values": {"quotex_time_mode": "TIMER", "quotex_host": "q.example"}},
        )
        # saving does not change a running application: it says "from the next start"
        assert rig.app.state.settings.quotex_time_mode == "TIME"

    async with running_api(tmp_path) as again:
        used = again.app.state.settings
        assert used.quotex_time_mode == "TIMER" and used.quotex_host == "q.example"
        assert used.port == 8000  # everything else is as the environment had it


async def test_the_engine_is_built_with_the_stored_settings(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []

    async with running_api(tmp_path) as rig:
        await rig.client.put(f"{API}/settings", json={"values": {"quotex_host": "stored.example"}})

    from app.main import create_app
    from tests.api_support import fake_builder, settings_for

    parts: list[Any] = []
    inner = fake_builder(parts)

    def spy(settings: Any, bus: Any, tasks: Any) -> Any:
        seen.append((settings.quotex_host, settings.quotex_time_mode))
        return inner(settings, bus, tasks)

    app = create_app(settings_for(tmp_path, engine_enabled=True), engine_builder=spy)
    async with app.router.lifespan_context(app):
        pass
    assert seen == [("stored.example", "TIME")]


async def test_null_removes_the_stored_value_and_the_environment_applies_again(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, quotex_host="qxbroker.example") as rig:
        await rig.client.put(f"{API}/settings", json={"values": {"quotex_host": "mine.example"}})
        cleared = await rig.client.put(f"{API}/settings", json={"values": {"quotex_host": None}})
        host = item(cleared.json(), "quotex_host")
        assert host["value"] == "qxbroker.example" and host["source"] == "environment"
        with sqlite3.connect(rig.settings.database_path) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM app_settings WHERE key LIKE 'config.%'"
            ).fetchone() == (0,)


@pytest.mark.parametrize(
    ("values", "fragment"),
    [
        ({"quotex_host": "not a host!"}, "domain"),
        ({"quotex_host": ""}, "domain"),
        ({"quotex_host": "https://quotex.com"}, "domain"),
        ({"quotex_time_mode": "SOMETIME"}, "TIME, TIMER"),
        ({"log_level": "LOUD"}, "DEBUG, INFO"),
        ({"engine_enabled": "true"}, "no setting called"),
        ({"quotex_allow_real": "true"}, "no setting called"),
        ({"secret_key": "x"}, "no setting called"),
    ],
)
async def test_bad_values_and_unknown_settings_are_refused_and_change_nothing(
    tmp_path: Path, values: dict[str, str], fragment: str
) -> None:
    async with running_api(tmp_path) as rig:
        response = await rig.client.put(
            f"{API}/settings", json={"values": {"log_level": "DEBUG", **values}}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_setting"
        assert fragment in response.json()["error"]["message"]
        body = (await rig.client.get(f"{API}/settings")).json()
        assert all(i["source"] == "default" for i in body["items"])  # not even the good one


async def test_an_empty_request_is_refused(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        assert (await rig.client.put(f"{API}/settings", json={"values": {}})).status_code == 422
        assert (await rig.client.put(f"{API}/settings", json={})).status_code == 422


async def test_a_damaged_stored_value_is_ignored_and_the_application_still_starts(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, quotex_host="qxbroker.example") as rig:
        db_path = rig.settings.database_path
    with sqlite3.connect(db_path) as db:
        for key, value in (
            ("config.quotex_host", '"bad host!!"'),
            ("config.log_level", "5"),
            ("config.not_a_setting", '"x"'),
        ):
            db.execute(
                "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, '2026-01-01')",
                (key, value),
            )
    async with running_api(tmp_path, quotex_host="qxbroker.example") as again:
        assert again.app.state.settings.quotex_host == "qxbroker.example"
        body = (await again.client.get(f"{API}/settings")).json()
        assert item(body, "quotex_host")["source"] == "environment"
        assert item(body, "log_level")["source"] == "default"


async def test_settings_do_not_disturb_the_risk_settings_stored_beside_them(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        await rig.client.put(f"{API}/risk/limits", json={"max_stake": "7.00"})
        await rig.client.put(f"{API}/settings", json={"values": {"log_level": "WARNING"}})
        controls = (await rig.client.get(f"{API}/risk")).json()["controls"]
        assert controls["limits"]["max_stake"] == "7.00"
    async with running_api(tmp_path) as again:
        assert (await again.client.get(f"{API}/risk")).json()["controls"]["limits"][
            "max_stake"
        ] == "7.00"
        assert again.app.state.settings.log_level == "WARNING"


async def test_the_settings_need_a_login(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        assert (await rig.client.get(f"{API}/settings")).status_code == 401
        put = await rig.client.put(f"{API}/settings", json={"values": {"log_level": "DEBUG"}})
        assert put.status_code == 401
