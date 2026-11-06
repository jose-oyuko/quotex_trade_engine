"""/api/v1/groups: create, read, edit, delete, pause/resume, per-group risk limits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.api_support import group_body, running_api

API = "/api/v1/groups"


async def test_a_group_can_be_created_read_listed_and_edited(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        created = await rig.create_group()
        assert created["id"] == 1
        assert created["title"] == "Signals A" and created["enabled"] is True
        assert created["paused"] is False and created["active_chains"] == 0
        assert created["settings"]["strategy"] == "martingale"
        assert created["settings"]["base_stake"] == "1.00"  # money is text, never a float
        assert created["settings"]["multipliers"] == ["2.0", "2.5"]

        assert (await rig.client.get(f"{API}/1")).json() == created
        listing = (await rig.client.get(API)).json()
        assert listing["total"] == 1 and listing["items"] == [created]

        edit = {
            "title": "Renamed",
            "enabled": False,
            "settings": group_body(
                settings={"strategy": "no_martingale", "max_steps": 0, "multipliers": []}
            )["settings"],
        }
        response = await rig.client.put(f"{API}/1", json=edit)
        assert response.status_code == 200
        edited = response.json()
        assert edited["title"] == "Renamed" and edited["enabled"] is False
        assert edited["settings"]["strategy"] == "no_martingale"
        assert edited["settings"]["multipliers"] == []
        assert (await rig.client.get(f"{API}/1")).json() == edited  # it was stored


async def test_the_list_is_paginated(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        for n in range(3):
            await rig.create_group(telegram_chat_id=-1000 - n, title=f"group {n}")
        page = (await rig.client.get(API, params={"limit": 2, "offset": 1})).json()
        assert page["total"] == 3 and page["limit"] == 2 and page["offset"] == 1
        assert [g["title"] for g in page["items"]] == ["group 1", "group 2"]
        assert (await rig.client.get(API, params={"limit": 0})).status_code == 422
        assert (await rig.client.get(API, params={"limit": 201})).status_code == 422


async def test_the_same_chat_cannot_be_added_twice(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await rig.create_group()
        response = await rig.client.post(API, json=group_body(title="Again"))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "group_exists"


async def test_a_missing_group_is_a_404_everywhere(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        body = group_body()
        edit = {k: body[k] for k in ("title", "enabled", "settings")}
        for response in (
            await rig.client.get(f"{API}/99"),
            await rig.client.put(f"{API}/99", json=edit),
            await rig.client.delete(f"{API}/99"),
            await rig.client.post(f"{API}/99/pause"),
            await rig.client.post(f"{API}/99/resume"),
            await rig.client.get(f"{API}/99/risk"),
            await rig.client.put(f"{API}/99/risk", json={}),
        ):
            assert response.status_code == 404, response.request.url
            assert response.json()["error"]["code"] == "group_not_found"


@pytest.mark.parametrize(
    ("change", "field", "fragment"),
    [
        ({"settings": {"max_steps": 3}}, "settings", "one multiplier per step"),
        ({"settings": {"multipliers": ["2.0", "0"]}}, "settings.multipliers.1", "greater than 0"),
        ({"settings": {"base_stake": "0"}}, "settings.base_stake", "greater than 0"),
        ({"settings": {"base_stake": "1.005"}}, "settings.base_stake", "decimal places"),
        ({"settings": {"min_payout_pct": 101}}, "settings.min_payout_pct", "less than or equal"),
        ({"settings": {"strategy": "yolo"}}, "settings.strategy", "Input should be"),
        ({"settings": {"max_steps": 21, "multipliers": ["2"] * 21}}, "settings.max_steps", "20"),
        ({"settings": {"nonsense": 1}}, "settings.nonsense", "Extra inputs"),
        ({"title": "   "}, "title", "at least 1"),
        ({"telegram_chat_id": 0}, "telegram_chat_id", "cannot be 0"),
        ({"telegram_chat_id": "abc"}, "telegram_chat_id", "integer"),
    ],
)
async def test_invalid_groups_are_refused_with_the_field_named(
    tmp_path: Path, change: dict[str, Any], field: str, fragment: str
) -> None:
    async with running_api(tmp_path) as rig:
        response = await rig.client.post(API, json=group_body(**change))
        assert response.status_code == 422, response.text
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        problems = {p["field"]: p["message"] for p in error["details"]}
        assert field in problems, problems
        assert fragment in problems[field]
        assert (await rig.client.get(API)).json()["total"] == 0  # nothing was stored


@pytest.mark.parametrize(
    ("settings", "fragment"),
    [
        ({"timezone": "Mars/Base"}, "not a UTC offset"),
        ({"parser": "telepathy"}, "unknown parser"),
    ],
)
async def test_values_the_domain_rejects_are_a_422_too(
    tmp_path: Path, settings: dict[str, Any], fragment: str
) -> None:
    async with running_api(tmp_path) as rig:
        response = await rig.client.post(API, json=group_body(settings=settings))
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "invalid_group" and fragment in error["message"]


async def test_a_group_with_no_history_can_be_deleted(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await rig.create_group()
        assert (await rig.client.delete(f"{API}/1")).status_code == 204
        assert (await rig.client.get(f"{API}/1")).status_code == 404
        assert (await rig.client.get(API)).json()["total"] == 0


async def test_a_group_with_history_cannot_be_deleted_only_disabled(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await rig.create_group()
        rig.fakes.signal(-1001, "EURUSD CALL 1m")
        await rig.eventually(_has_signals(rig))
        await rig.fakes.engine.manager.wait_idle(5)
        response = await rig.client.delete(f"{API}/1")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "group_in_use"
        assert "disable" in response.json()["error"]["message"]


async def test_a_group_with_a_running_chain_cannot_be_deleted(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        await rig.create_group()
        rig.fakes.signal(-1001, "EURUSD CALL 1m")
        await rig.eventually(_chain_running(rig))
        response = await rig.client.delete(f"{API}/1")
        assert response.status_code == 409
        assert "running chains" in response.json()["error"]["message"]


def _has_signals(rig):  # type: ignore[no-untyped-def]
    async def check() -> bool:
        return (await rig.client.get("/api/v1/signals")).json()["total"] > 0

    return check


def _chain_running(rig):  # type: ignore[no-untyped-def]
    async def check() -> bool:
        return len(rig.fakes.engine.manager.active_chains()) > 0

    return check


# --- the engine learns about edits at once ---


async def test_a_new_group_starts_trading_without_a_restart_and_a_disabled_one_stops(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await rig.create_group()
        rig.fakes.signal(-1001, "EURUSD CALL 1m")
        await rig.eventually(_order_count(rig, 1))

        edit = {"title": "Signals A", "enabled": False, "settings": group_body()["settings"]}
        assert (await rig.client.put(f"{API}/1", json=edit)).status_code == 200
        assert not rig.fakes.source.emit(-1001, "GBPUSD CALL 1m", message_id=99)  # unsubscribed

        edit["enabled"] = True
        assert (await rig.client.put(f"{API}/1", json=edit)).status_code == 200
        rig.fakes.signal(-1001, "GBPUSD CALL 1m")
        await rig.eventually(_order_count(rig, 2))


def _order_count(rig, count: int):  # type: ignore[no-untyped-def]
    async def check() -> bool:
        return len(rig.fakes.adapter.orders) >= count

    return check


async def test_editing_a_group_does_not_change_a_chain_that_is_already_running(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        await rig.create_group()
        rig.fakes.signal(-1001, "EURUSD CALL 1m")
        await rig.eventually(_order_count(rig, 1))
        edit = {
            "title": "Signals A",
            "enabled": True,
            "settings": group_body(settings={"base_stake": "9.00"})["settings"],
        }
        assert (await rig.client.put(f"{API}/1", json=edit)).status_code == 200
        [chain] = rig.fakes.engine.manager.active_chains()
        assert str(chain.to_record().base_stake) == "1.00"  # snapshotted when it started (D-10)
        rig.fakes.signal(-1001, "GBPUSD CALL 1m")  # a new chain uses the new settings
        await rig.eventually(_order_count(rig, 2))
        assert [str(o.amount) for o in rig.fakes.adapter.orders] == ["1.00", "9.00"]


# --- the opposite pair (D-70) ---

FLIP_PAIR = {
    "strategy": "flip_every_loss",
    "allow_opposite_pair": True,
    "max_steps": 1,
    "multipliers": ["2.0"],
}


async def test_the_opposite_pair_is_off_by_default_and_can_be_switched_on_and_off(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        created = await rig.create_group(settings={"strategy": "flip_every_loss"})
        assert created["settings"]["allow_opposite_pair"] is False

        edit = {
            "title": "Signals A",
            "enabled": True,
            "settings": group_body(settings=FLIP_PAIR)["settings"],
        }
        edited = (await rig.client.put(f"{API}/1", json=edit)).json()
        assert edited["settings"]["allow_opposite_pair"] is True
        assert (await rig.client.get(f"{API}/1")).json()["settings"]["allow_opposite_pair"] is True

        edit["settings"]["allow_opposite_pair"] = False
        edited = (await rig.client.put(f"{API}/1", json=edit)).json()
        assert edited["settings"]["allow_opposite_pair"] is False


@pytest.mark.parametrize("strategy", ["martingale", "no_martingale"])
async def test_the_opposite_pair_is_refused_for_strategies_that_do_not_need_it(
    tmp_path: Path, strategy: str
) -> None:
    async with running_api(tmp_path) as rig:
        body = group_body(settings={"strategy": strategy, "allow_opposite_pair": True})
        response = await rig.client.post(API, json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_group"
        assert "flip strategies only" in response.json()["error"]["message"]
        assert (await rig.client.get(API)).json()["total"] == 0


async def test_a_group_set_up_for_the_pair_places_both_opposite_orders(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        await rig.create_group(settings=FLIP_PAIR)
        rig.fakes.signal(-1001, "EURUSD CALL 1m")
        rig.fakes.signal(-1001, "EURUSD PUT 1m")
        await rig.eventually(_order_count(rig, 2))
        assert [o.direction.value for o in rig.fakes.adapter.orders] == ["call", "put"]
        assert len(rig.fakes.engine.manager.active_chains(1)) == 2
        assert (await rig.client.get(f"{API}/1")).json()["active_chains"] == 2


# --- pause and resume ---


async def test_pausing_a_group_is_visible_and_resuming_undoes_it(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await rig.create_group()
        paused = (await rig.client.post(f"{API}/1/pause")).json()
        assert paused["paused"] is True
        assert (await rig.client.get(f"{API}/1")).json()["paused"] is True
        assert (await rig.client.post(f"{API}/1/pause")).json()["paused"] is True  # idempotent
        rig.fakes.signal(-1001, "EURUSD CALL 1m")
        await rig.eventually(_has_signals(rig))
        assert rig.fakes.adapter.orders == []

        assert (await rig.client.post(f"{API}/1/resume")).json()["paused"] is False
        rig.fakes.signal(-1001, "GBPUSD CALL 1m")
        await rig.eventually(_order_count(rig, 1))


async def test_pause_needs_the_engine(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await rig.create_group()
        response = await rig.client.post(f"{API}/1/pause")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "engine_not_running"


# --- per-group risk limits ---


async def test_group_risk_limits_can_be_set_with_or_without_the_engine(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:  # no engine: limits are set before it is enabled
        await rig.create_group()
        empty = (await rig.client.get(f"{API}/1/risk")).json()
        assert empty == {"max_stake": None, "daily_stop_loss": None, "daily_profit_target": None}
        body = {"max_stake": "5.00", "daily_stop_loss": "20.00", "daily_profit_target": None}
        response = await rig.client.put(f"{API}/1/risk", json=body)
        assert response.status_code == 200 and response.json() == body
        assert (await rig.client.get(f"{API}/1/risk")).json() == body


async def test_group_risk_limits_are_validated(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await rig.create_group()
        for bad in ({"max_stake": "0"}, {"max_stake": "-1"}, {"daily_stop_loss": "abc"}, {"x": 1}):
            response = await rig.client.put(f"{API}/1/risk", json=bad)
            assert response.status_code == 422, bad


async def test_group_limits_set_through_the_api_are_enforced_by_the_engine(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await rig.create_group()
        await rig.client.put(f"{API}/1/risk", json={"max_stake": "0.50"})
        rig.fakes.signal(-1001, "EURUSD CALL 1m")  # the base stake of 1.00 is over the maximum
        await rig.eventually(_risk_event(rig))
        assert rig.fakes.adapter.orders == []


def _risk_event(rig):  # type: ignore[no-untyped-def]
    async def check() -> bool:
        items = (await rig.client.get("/api/v1/risk/events")).json()["items"]
        return any(e["kind"] == "group_max_stake" for e in items)

    return check
