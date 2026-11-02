"""/api/v1 risk, kill switch, chain commands, account, status and health."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db.engine import create_engine, create_session_factory
from app.db.repositories import AppSettingsRepository
from app.quotex.base import TradeOutcome
from tests.api_support import ApiRig, running_api

API = "/api/v1"
LIMITS: dict[str, Any] = {
    "max_stake": "10.00",
    "max_concurrent_trades": 3,
    "max_exposure": "25.00",
    "max_chain_trades": 4,
    "daily_stop_loss": "30.00",
    "daily_profit_target": None,
    "reset_timezone": "UTC-3",
    "reset_time": "06:00",
}


async def start_running_chain(rig: ApiRig, text: str = "EURUSD CALL 1m") -> str:
    """Emit a signal on a held-results engine and return the id of the chain it starts."""
    rig.fakes.signal(-1001, text)

    async def started() -> bool:
        return bool(rig.fakes.adapter.orders) and any(
            c.status.value == "open" for c in rig.fakes.engine.manager.active_chains()
        )

    await rig.eventually(started)
    return str(rig.fakes.engine.manager.active_chains()[-1].id)


# --- risk limits ---


async def test_global_limits_round_trip_and_default_to_none(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        risk = (await rig.client.get(f"{API}/risk")).json()
        assert risk["controls"]["limits"] == {
            "max_stake": None,
            "max_concurrent_trades": None,
            "max_exposure": None,
            "max_chain_trades": None,
            "daily_stop_loss": None,
            "daily_profit_target": None,
            "reset_timezone": "UTC",
            "reset_time": "00:00",
        }
        assert risk["controls"]["kill_switch"] is False
        assert risk["day"] is None and risk["open_trades"] is None  # no engine

        response = await rig.client.put(f"{API}/risk/limits", json=LIMITS)
        assert response.status_code == 200
        assert response.json() == {**LIMITS, "reset_time": "06:00"}
        assert (await rig.client.get(f"{API}/risk")).json()["controls"]["limits"] == response.json()


async def test_limits_set_before_the_engine_exists_are_stored_for_it(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        assert (await rig.client.put(f"{API}/risk/limits", json=LIMITS)).status_code == 200
    # the application is stopped: the setting is in the database, where a later start reads it
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'data' / 'quotex.db').as_posix()}")
    try:
        async with create_session_factory(engine)() as session:
            keys = {s.key for s in await AppSettingsRepository(session).all()}
    finally:
        await engine.dispose()
    assert keys == {"risk.limits"}


async def test_limits_are_validated(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        for bad in (
            {"max_stake": "0"},
            {"max_stake": "-5"},
            {"max_stake": "12.345"},
            {"max_concurrent_trades": 0},
            {"max_chain_trades": 101},
            {"reset_time": "04:30:15"},
            {"reset_time": "not a time"},
            {"surprise": True},
        ):
            response = await rig.client.put(f"{API}/risk/limits", json=bad)
            assert response.status_code == 422, bad
            assert response.json()["error"]["code"] == "validation_error"
        unknown_zone = await rig.client.put(f"{API}/risk/limits", json={"reset_timezone": "Mars"})
        assert unknown_zone.status_code == 422
        assert unknown_zone.json()["error"]["code"] == "invalid_risk_limits"
        # none of that changed anything
        assert (await rig.client.get(f"{API}/risk")).json()["controls"]["limits"][
            "max_stake"
        ] is None


async def test_limits_set_through_the_api_block_orders_and_are_listed_as_risk_events(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await rig.create_group()
        await rig.client.put(f"{API}/risk/limits", json={"max_stake": "0.50"})
        rig.fakes.signal(-1001, "EURUSD CALL 1m")

        async def listed() -> bool:
            return (await rig.client.get(f"{API}/risk/events")).json()["total"] >= 1

        await rig.eventually(listed)
        assert rig.fakes.adapter.orders == []
        [event] = (await rig.client.get(f"{API}/risk/events")).json()["items"]
        assert event["kind"] == "max_stake" and event["group_id"] == 1
        assert event["message"].startswith("order not sent:")
        assert event["details"]["stake"] == "1.00"


async def test_risk_events_are_paginated(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await rig.create_group()
        await rig.client.put(f"{API}/risk/limits", json={"max_stake": "0.50"})
        for asset in ("EURUSD", "GBPUSD", "USDJPY"):
            rig.fakes.signal(-1001, f"{asset} CALL 1m")

        async def three() -> bool:
            return (await rig.client.get(f"{API}/risk/events")).json()["total"] == 3

        await rig.eventually(three)
        page = (await rig.client.get(f"{API}/risk/events", params={"limit": 2})).json()
        assert len(page["items"]) == 2 and page["total"] == 3
        assert (await rig.client.get(f"{API}/risk/events", params={"limit": 0})).status_code == 422


async def test_editing_limits_keeps_todays_result_so_it_is_no_way_out_of_a_stop_loss(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await rig.create_group(
            settings={"strategy": "no_martingale", "max_steps": 0, "multipliers": []}
        )
        await rig.client.put(f"{API}/risk/limits", json={"daily_stop_loss": "1.00"})
        rig.fakes.adapter.script_results(TradeOutcome.LOST)
        rig.fakes.signal(-1001, "EURUSD CALL 1m")
        await rig.fakes.engine.manager.wait_idle(5)
        day = (await rig.client.get(f"{API}/risk")).json()["day"]
        assert day["pnl"].startswith("-")
        await rig.client.put(
            f"{API}/risk/limits", json={"daily_stop_loss": "1.00", "max_stake": "50"}
        )
        assert (await rig.client.get(f"{API}/risk")).json()["day"]["pnl"] == day["pnl"]


# --- kill switch ---


async def test_the_kill_switch_stops_orders_and_can_be_released(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await rig.create_group()
        engaged = await rig.client.post(f"{API}/kill-switch")
        assert engaged.status_code == 200 and engaged.json()["kill_switch"] is True
        assert (await rig.client.post(f"{API}/kill-switch")).json()["kill_switch"] is True  # again
        assert (await rig.client.get(f"{API}/risk")).json()["controls"]["kill_switch"] is True
        assert (await rig.client.get(f"{API}/status")).json()["controls"]["kill_switch"] is True

        rig.fakes.signal(-1001, "EURUSD CALL 1m")

        async def ignored() -> bool:
            rows = (await rig.client.get(f"{API}/signals")).json()["items"]
            return any(r["status"] == "ignored" for r in rows)

        await rig.eventually(ignored)
        assert rig.fakes.adapter.orders == []

        released = await rig.client.delete(f"{API}/kill-switch")
        assert released.json()["kill_switch"] is False
        assert (await rig.client.delete(f"{API}/kill-switch")).json()["kill_switch"] is False
        rig.fakes.signal(-1001, "GBPUSD CALL 1m")

        async def traded() -> bool:
            return len(rig.fakes.adapter.orders) == 1

        await rig.eventually(traded)


async def test_the_kill_switch_can_end_the_running_chains_at_once(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        await rig.create_group()
        chain_id = await start_running_chain(rig)
        response = await rig.client.post(f"{API}/kill-switch", json={"stop_chains": True})
        assert response.status_code == 200
        assert rig.fakes.engine.manager.active_chains() == []

        async def stored() -> bool:
            row = (await rig.client.get(f"{API}/chains/{chain_id}")).json()
            return (
                row.get("chain", {}).get("status") == "stopped"
            )  # 404 until the writer has stored it

        await rig.eventually(stored)
        bad = await rig.client.post(f"{API}/kill-switch", json={"stop_chains": "perhaps"})
        assert bad.status_code == 422


async def test_the_kill_switch_needs_the_engine(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        for response in (
            await rig.client.post(f"{API}/kill-switch"),
            await rig.client.delete(f"{API}/kill-switch"),
            await rig.client.put(f"{API}/account", json={"account_type": "demo"}),
            await rig.client.post(f"{API}/chains/{uuid4()}/end"),
            await rig.client.post(f"{API}/chains/{uuid4()}/stop-after-current"),
        ):
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "engine_not_running"


# --- chain commands ---


async def test_stop_after_current_lets_the_open_trade_settle_and_ends_the_chain(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        await rig.create_group()
        rig.fakes.adapter.script_results(
            TradeOutcome.LOST
        )  # a loss would normally start a follow-up
        chain_id = await start_running_chain(rig)
        response = await rig.client.post(f"{API}/chains/{chain_id}/stop-after-current")
        assert response.status_code == 200
        body = response.json()
        assert body["stop_requested"] is True and body["chain"]["id"] == chain_id
        assert body["chain"]["status"] == "open"  # still running until its trade settles
        again = await rig.client.post(f"{API}/chains/{chain_id}/stop-after-current")
        assert again.status_code == 200 and again.json()["stop_requested"] is True  # harmless

        rig.fakes.adapter.settle(rig.fakes.adapter.orders[-1].order_id)
        await rig.fakes.engine.manager.wait_idle(5)
        assert len(rig.fakes.adapter.orders) == 1  # no follow-up

        async def ended() -> bool:
            row = (await rig.client.get(f"{API}/chains/{chain_id}")).json()
            return (
                row.get("chain", {}).get("status") == "stopped"
            )  # 404 until the writer has stored it

        await rig.eventually(ended)
        gone = await rig.client.post(f"{API}/chains/{chain_id}/stop-after-current")
        assert gone.status_code == 409
        assert gone.json()["error"]["code"] == "chain_not_running"
        assert "stopped" in gone.json()["error"]["message"]


async def test_ending_a_chain_frees_the_group_now_and_the_open_trade_is_still_recorded(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        await rig.create_group(settings={"strategy": "flip_every_loss"})
        chain_id = await start_running_chain(rig)
        group = (await rig.client.get(f"{API}/groups/1")).json()
        assert group["active_chains"] == 1

        response = await rig.client.post(f"{API}/chains/{chain_id}/end")
        assert response.status_code == 200
        assert response.json()["chain"]["status"] == "stopped"
        assert (await rig.client.get(f"{API}/groups/1")).json()["active_chains"] == 0
        # a flip strategy ignores signals while a chain runs; the group is free again
        await start_running_chain(rig, "GBPUSD PUT 1m")
        assert len(rig.fakes.adapter.orders) == 2

        again = await rig.client.post(f"{API}/chains/{chain_id}/end")
        assert again.status_code == 409 and again.json()["error"]["code"] == "chain_not_running"
        rig.fakes.adapter.settle_all()
        await rig.fakes.engine.manager.wait_idle(5)

        async def recorded() -> bool:
            rows = (await rig.client.get(f"{API}/trades")).json()["items"]
            return len(rows) == 2 and all(t["status"] == "won" for t in rows)

        await rig.eventually(recorded)


async def test_commands_on_a_chain_that_never_existed_are_a_404(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        for command in ("end", "stop-after-current"):
            response = await rig.client.post(f"{API}/chains/{uuid4()}/{command}")
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "chain_not_found"
        assert (await rig.client.post(f"{API}/chains/nope/end")).status_code == 422


# --- account ---


async def test_the_account_can_be_read_and_switched_when_nothing_is_running(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True, quotex_allow_real=True) as rig:
        assert (await rig.client.get(f"{API}/account")).json() == {
            "account_type": "demo",
            "real_trading_allowed": True,
        }
        response = await rig.client.put(f"{API}/account", json={"account_type": "real"})
        assert response.status_code == 200 and response.json()["account_type"] == "real"
        assert (await rig.client.get(f"{API}/status")).json()["account_type"] == "real"
        back = await rig.client.put(f"{API}/account", json={"account_type": "demo"})
        assert back.json()["account_type"] == "demo"
        assert (
            await rig.client.put(f"{API}/account", json={"account_type": "paper"})
        ).status_code == 422


async def test_switching_to_real_is_refused_unless_it_was_switched_on_in_the_settings(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        response = await rig.client.put(f"{API}/account", json={"account_type": "real"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "real_trading_not_allowed"
        assert (await rig.client.get(f"{API}/account")).json()["account_type"] == "demo"


async def test_the_account_cannot_be_switched_while_a_chain_is_running(tmp_path: Path) -> None:
    async with running_api(
        tmp_path, with_engine=True, hold_results=True, quotex_allow_real=True
    ) as rig:
        await rig.create_group()
        await start_running_chain(rig)
        response = await rig.client.put(f"{API}/account", json={"account_type": "real"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "account_switch_refused"
        assert (await rig.client.get(f"{API}/account")).json()["account_type"] == "demo"


# --- status and health ---


async def test_status_without_an_engine_is_an_honest_empty_picture(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        status = (await rig.client.get(f"{API}/status")).json()
        assert status["engine"] == {"enabled": False, "running": False}
        assert status["account_type"] == "demo" and status["real_trading_allowed"] is False
        assert status["connections"] == {} and status["balance"] is None
        assert status["open_chains"] == [] and status["open_trades"] == []
        assert status["day"] is None
        assert status["version"] and status["environment"] == "development"


async def test_status_with_an_engine_shows_connections_balance_and_what_is_open(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        await rig.create_group()
        await start_running_chain(rig)

        async def complete() -> bool:
            status = (await rig.client.get(f"{API}/status")).json()
            return (
                {"telegram", "quotex"} <= set(status["connections"])
                and status["balance"] is not None
                and len(status["open_chains"]) == 1
                and len(status["open_trades"]) == 1
            )

        await rig.eventually(complete)
        status = (await rig.client.get(f"{API}/status")).json()
        assert status["engine"] == {"enabled": True, "running": True}
        assert status["connections"]["quotex"]["connected"] is True
        assert status["connections"]["telegram"]["connected"] is True
        assert status["balance"]["account_type"] == "demo"
        assert status["open_chains"][0]["status"] == "open"
        assert status["open_trades"][0]["status"] == "open"
        assert status["day"]["account_type"] == "demo" and status["day"]["pnl"] == "0"

        rig.fakes.adapter.settle_all()
        await rig.fakes.engine.manager.wait_idle(5)

        async def nothing_open() -> bool:
            status = (await rig.client.get(f"{API}/status")).json()
            return not status["open_chains"] and not status["open_trades"]

        await rig.eventually(nothing_open)


async def test_health_reports_the_engine_and_the_connections(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        health = (await rig.client.get(f"{API}/health")).json()
        assert health["status"] == "ok" and health["database"] == "ok"
        assert health["engine"] == {"enabled": False, "running": False}
        assert health["telegram"] is None and health["quotex"] is None
        assert health["ws_clients"] == 0
    async with running_api(tmp_path / "second", with_engine=True) as rig:

        async def reported() -> bool:
            health = (await rig.client.get(f"{API}/health")).json()
            return bool(health["quotex"] and health["telegram"] and health["last_event_at"])

        await rig.eventually(reported)
        health = (await rig.client.get(f"{API}/health")).json()
        assert health["engine"] == {"enabled": True, "running": True}
        assert health["quotex"]["connected"] is True
