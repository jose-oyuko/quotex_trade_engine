"""/api/v1/sessions: set up, edit, delete, start now, stop, and the runs on record (D-71..D-73)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from tests.api_support import ApiRig, running_api

API = "/api/v1/sessions"


def session_body(**overrides: Any) -> dict[str, Any]:
    """A valid session: weekdays 11:00-12:00 UTC on EURUSD, M5, flip strategy."""
    body: dict[str, Any] = {
        "name": "London open",
        "enabled": True,
        "asset": "EURUSD",
        "duration_s": 300,
        "start_time": "11:00",
        "end_time": "12:00",
        "timezone": "UTC",
        "repeat": "weekdays",
        "weekdays": [0, 1, 2, 3, 4],
        "pause_s": 0,
        "profit_target": "10.00",
        "loss_limit": "20.00",
        "max_pairs": None,
        "strategy": {
            "strategy": "flip_every_loss",
            "base_stake": "1.00",
            "max_steps": 2,
            "multipliers": ["2.0", "3.0"],
            "min_payout_pct": 0,
        },
    }
    strategy = overrides.pop("strategy", {})
    body.update(overrides)
    body["strategy"] = {**body["strategy"], **strategy}
    return body


async def create(rig: ApiRig, **overrides: Any) -> dict[str, Any]:
    response = await rig.client.post(API, json=session_body(**overrides))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def test_a_session_can_be_created_read_listed_edited_and_deleted(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        created = await create(rig)
        assert created["id"] == 1 and created["name"] == "London open"
        assert created["asset"] == "EURUSD" and created["duration_s"] == 300
        assert created["start_time"] == "11:00:00" and created["end_time"] == "12:00:00"
        assert created["weekdays"] == [0, 1, 2, 3, 4]
        assert created["profit_target"] == "10.00" and created["loss_limit"] == "20.00"
        assert created["strategy"]["multipliers"] == ["2.0", "3.0"]
        assert created["strategy"]["base_stake"] == "1.00"  # money is text, never a float
        assert created["active_run"] is None
        assert created["next_window_start"] is not None  # it is enabled: it has a next window

        assert (await rig.client.get(f"{API}/1")).json() == created
        listing = (await rig.client.get(API)).json()
        assert listing["total"] == 1 and listing["items"] == [created]

        edit = session_body(name="Renamed", enabled=False, strategy={"base_stake": "2.00"})
        response = await rig.client.put(f"{API}/1", json=edit)
        assert response.status_code == 200, response.text
        edited = response.json()
        assert edited["name"] == "Renamed" and edited["enabled"] is False
        assert edited["strategy"]["base_stake"] == "2.00"
        assert edited["next_window_start"] is None  # switched off: it will not start by itself

        assert (await rig.client.delete(f"{API}/1")).status_code == 204
        assert (await rig.client.get(f"{API}/1")).status_code == 404
        assert (await rig.client.get(API)).json()["total"] == 0


async def test_the_hidden_group_of_a_session_is_not_a_group(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        created = await create(rig)
        assert (await rig.client.get("/api/v1/groups")).json()["total"] == 0
        response = await rig.client.get(f"/api/v1/groups/{created['group_id']}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "group_not_found"
        # a real Telegram group can still be added, next to it
        await rig.create_group()
        assert (await rig.client.get("/api/v1/groups")).json()["total"] == 1


async def test_the_form_says_what_it_does_not_like(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        cases = {
            "an unknown trade length": session_body(duration_s=45),
            "an asset name that is not one": session_body(asset="eur/usd"),
            "a window that starts and ends together": session_body(
                start_time="11:00", end_time="11:00"
            ),
            "an unknown time zone": session_body(timezone="Mars/Olympus"),
            "no day chosen": session_body(weekdays=[]),
            "a day that does not exist": session_body(weekdays=[7]),
            "a target of zero": session_body(profit_target="0"),
            "a multiplier missing": session_body(strategy={"max_steps": 3}),
        }
        for what, body in cases.items():
            response = await rig.client.post(API, json=body)
            assert response.status_code == 422, what
        invalid = await rig.client.post(API, json=session_body(duration_s=45))
        assert invalid.json()["error"]["code"] == "invalid_session"
        assert "5 min" in invalid.json()["error"]["message"]  # it lists what is allowed


async def test_a_once_session_needs_no_days(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        created = await create(rig, repeat="once", weekdays=[])
        assert created["repeat"] == "once" and created["next_window_start"] is not None


# --- one session at a time ---


async def test_two_enabled_sessions_may_not_overlap(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await create(rig)
        clash = await rig.client.post(
            API, json=session_body(name="Clash", start_time="11:30", end_time="12:30")
        )
        assert clash.status_code == 409
        assert clash.json()["error"]["code"] == "session_overlap"
        assert "London open" in clash.json()["error"]["message"]

        # touching is fine, so is another day, and so is a switched-off session
        await create(rig, name="After", start_time="12:00", end_time="13:00")
        await create(rig, name="Weekend", start_time="11:00", end_time="12:00", weekdays=[5, 6])
        await create(rig, name="Off", enabled=False, start_time="11:30", end_time="12:30")
        assert (await rig.client.get(API)).json()["total"] == 4


async def test_overlap_is_found_across_midnight_and_when_a_session_is_enabled_again(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        await create(
            rig, name="Late", start_time="23:00", end_time="01:00", weekdays=[0, 1, 2, 3, 4]
        )
        early = await rig.client.post(
            API, json=session_body(name="Early", start_time="00:30", end_time="02:00")
        )
        assert early.status_code == 409

        off = await create(rig, name="Off", enabled=False, start_time="00:30", end_time="02:00")
        again = await rig.client.put(
            f"{API}/{off['id']}",
            json=session_body(name="Off", enabled=True, start_time="00:30", end_time="02:00"),
        )
        assert again.status_code == 409  # switching it on would overlap


async def test_a_session_can_be_edited_without_clashing_with_itself(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        created = await create(rig)
        response = await rig.client.put(
            f"{API}/{created['id']}", json=session_body(loss_limit="5.00")
        )
        assert response.status_code == 200 and response.json()["loss_limit"] == "5.00"


async def test_warnings_say_when_the_start_is_off_a_candle_or_nothing_stops_the_session(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        plain = await create(rig)
        assert plain["warnings"] == []  # 11:00 is a candle start and both limits are set

        off_candle = await create(
            rig,
            name="Off candle",
            start_time="14:02",
            end_time="15:00",
            profit_target=None,
            loss_limit=None,
        )
        text = " ".join(off_candle["warnings"])
        assert "candle boundary" in text and "No profit target" in text


# --- running ---


async def test_a_session_can_be_started_and_stopped_by_hand(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        created = await create(rig)
        engine = rig.fakes.engine
        started = await rig.client.post(f"{API}/{created['id']}/start")
        assert started.status_code == 200, started.text
        run = started.json()
        assert run["started_by"] == "manual" and run["state"] == "running"
        assert run["account_type"] == "demo"

        await rig.eventually(_orders(rig, 2))  # the pair went out at once: CALL and PUT
        assert [o.direction.value for o in rig.fakes.adapter.orders] == ["call", "put"]

        again = await rig.client.post(f"{API}/{created['id']}/start")
        assert again.status_code == 409 and again.json()["error"]["code"] == "session_run_active"
        shown = (await rig.client.get(f"{API}/{created['id']}")).json()
        assert shown["active_run"]["id"] == run["id"]

        # edits and deletes wait until it is over
        edit = await rig.client.put(f"{API}/{created['id']}", json=session_body())
        assert edit.status_code == 409 and edit.json()["error"]["code"] == "session_in_use"
        assert (await rig.client.delete(f"{API}/{created['id']}")).status_code == 409

        stopped = await rig.client.post(f"{API}/{created['id']}/stop")
        assert stopped.status_code == 200 and stopped.json()["state"] == "stopping"
        assert len(engine.manager.active_chains()) == 2  # the chains are not cut off

        for order in rig.fakes.adapter.orders:
            rig.fakes.adapter.settle(order.order_id)
        await rig.eventually(_run_ended(rig, run["id"]))
        runs = (await rig.client.get(f"{API}/runs")).json()
        assert runs["total"] == 1
        assert runs["items"][0]["end_reason"] == "stopped"
        assert runs["items"][0]["pairs_opened"] == 1


def _orders(rig: ApiRig, count: int) -> Any:
    async def check() -> bool:
        return len(rig.fakes.adapter.orders) >= count

    return check


def _run_ended(rig: ApiRig, run_id: str) -> Any:
    async def check() -> bool:
        runs = (await rig.client.get(f"{API}/runs")).json()["items"]
        return any(r["id"] == run_id and r["state"] == "ended" for r in runs)

    return check


async def test_starting_needs_the_engine_and_an_enabled_session(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:  # the engine is not running
        created = await create(rig)
        response = await rig.client.post(f"{API}/{created['id']}/start")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "engine_not_running"

    async with running_api(tmp_path / "again", with_engine=True) as rig:
        off = await create(rig, enabled=False)
        response = await rig.client.post(f"{API}/{off['id']}/start")
        assert response.status_code == 422 and "switched off" in response.json()["error"]["message"]


async def test_stopping_a_session_that_is_not_running_says_so(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        created = await create(rig)
        response = await rig.client.post(f"{API}/{created['id']}/stop")
        assert response.status_code == 409 and response.json()["error"]["code"] == "no_active_run"
        assert (await rig.client.post(f"{API}/99/stop")).status_code == 404
        assert (await rig.client.post(f"{API}/99/start")).status_code == 404


async def test_a_session_with_runs_on_record_cannot_be_deleted(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        created = await create(
            rig
        )  # results settle at once here: the run goes on to its next candle
        await rig.client.post(f"{API}/{created['id']}/start")
        await rig.eventually(_orders(rig, 2))
        await rig.client.post(f"{API}/{created['id']}/stop")
        await rig.eventually(_idle(rig))

        response = await rig.client.delete(f"{API}/{created['id']}")
        assert response.status_code == 409 and response.json()["error"]["code"] == "session_in_use"
        assert "disable it" in response.json()["error"]["message"]


def _idle(rig: ApiRig) -> Any:
    async def check() -> bool:
        return rig.fakes.engine.scheduler.active_run is None

    return check


async def test_the_runs_list_can_be_filtered_and_an_unknown_session_is_a_404(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        await create(rig)
        assert (await rig.client.get(f"{API}/runs")).json()["total"] == 0
        assert (await rig.client.get(f"{API}/runs", params={"session_id": 1})).status_code == 200
        missing = await rig.client.get(f"{API}/runs", params={"session_id": 9})
        assert missing.status_code == 404


async def test_a_session_saved_while_the_engine_runs_is_known_to_it(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        created = await create(rig)
        engine = rig.fakes.engine
        assert created["id"] in engine.scheduler._sessions


async def test_the_session_routes_need_a_login(tmp_path: Path) -> None:
    async with running_api(tmp_path, logged_in=False) as rig:
        for method, path in (
            ("GET", API),
            ("POST", API),
            ("GET", f"{API}/runs"),
            ("GET", f"{API}/1"),
            ("PUT", f"{API}/1"),
            ("DELETE", f"{API}/1"),
            ("POST", f"{API}/1/start"),
            ("POST", f"{API}/1/stop"),
        ):
            response = await rig.client.request(method, path)
            assert response.status_code == 401, (method, path)


async def test_a_run_whose_window_passed_while_the_app_was_down_ends_as_interrupted(
    tmp_path: Path,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.db.repositories import SessionRepository
    from app.domain.enums import RunState
    from tests.factories import make_session_run
    from tests.integration.test_session_storage import add_session

    ids: dict[str, Any] = {}

    async def seed(factory: async_sessionmaker[AsyncSession]) -> None:
        _, saved = await add_session(factory, id=None)
        assert saved.id is not None
        run = make_session_run(saved.id, state=RunState.RUNNING)
        async with factory.begin() as db:
            await SessionRepository(db).upsert_run(run)
        ids["run"], ids["session"] = str(run.id), saved.id

    async with running_api(tmp_path, with_engine=True, hold_results=True, seed=seed) as rig:

        async def interrupted() -> bool:
            runs = (await rig.client.get(f"{API}/runs")).json()["items"]
            return any(
                r["id"] == ids["run"]
                and r["state"] == "ended"
                and r["end_reason"] == "interrupted"
                and "its window ended in the meantime" in (r["note"] or "")
                for r in runs
            )

        await rig.eventually(interrupted)
        assert rig.fakes.engine.scheduler.active_run is None  # nothing was resumed
        assert rig.fakes.adapter.orders == []


async def test_pairs_can_be_spaced_one_at_a_time_or_at_every_candle(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        plain = await create(rig)
        assert plain["mode"] == "sequential" and plain["max_open_pairs"] == 1

        candle = await create(
            rig,
            name="Candles",
            start_time="13:00",
            end_time="14:00",
            mode="every_candle",
            max_open_pairs=3,
        )
        assert candle["mode"] == "every_candle" and candle["max_open_pairs"] == 3
        assert (await rig.client.get(f"{API}/{candle['id']}")).json()["max_open_pairs"] == 3

        edited = await rig.client.put(
            f"{API}/{candle['id']}",
            json=session_body(
                name="Candles", start_time="13:00", end_time="14:00", mode="sequential"
            ),
        )
        assert edited.json()["mode"] == "sequential" and edited.json()["max_open_pairs"] == 1


async def test_the_open_pair_limit_must_be_a_sensible_number(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        for bad in (0, -1, 51):
            response = await rig.client.post(
                API, json=session_body(mode="every_candle", max_open_pairs=bad)
            )
            assert response.status_code == 422, bad
        unknown = await rig.client.post(API, json=session_body(mode="all_at_once"))
        assert unknown.status_code == 422


async def test_a_session_in_candle_mode_opens_pairs_through_the_api(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        created = await create(rig, mode="every_candle", max_open_pairs=2)
        started = await rig.client.post(f"{API}/{created['id']}/start")
        assert started.status_code == 200, started.text
        await rig.eventually(_orders(rig, 2))
        assert len(rig.fakes.engine.scheduler._sessions) == 1
        stopped = await rig.client.post(f"{API}/{created['id']}/stop")
        assert stopped.status_code == 200


# --- the broker (decision D-75) ---


async def test_a_deriv_session_takes_deriv_names_and_its_hidden_group_trades_there(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        created = await create(rig, broker="deriv", asset="R_75", duration_s=60)
        assert created["broker"] == "deriv" and created["asset"] == "R_75"
        assert (await create(rig, name="Quotex one", start_time="13:00", end_time="14:00"))[
            "broker"
        ] == "quotex"
        with sqlite3.connect(rig.settings.database_path) as db:
            brokers = dict(db.execute("SELECT title, broker FROM groups"))
        assert brokers == {"Session: London open": "deriv", "Session: Quotex one": "quotex"}


async def test_a_deriv_session_refuses_otc_pairs_and_quotex_refuses_deriv_names(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        otc = await rig.client.post(
            API, json=session_body(broker="deriv", asset="EURUSD_otc", duration_s=900)
        )
        assert otc.status_code == 422
        assert "Deriv has none" in otc.json()["error"]["message"]
        index = await rig.client.post(API, json=session_body(asset="R_75", duration_s=60))
        assert index.status_code == 422
        assert "not a Quotex asset name" in index.json()["error"]["message"]
