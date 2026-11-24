"""/api/v1/backtests (decision D-84): a session-shaped setup replayed on stored (made-up) prices,
and the service's one-at-a-time, cancel and restart rules."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.api.routers.backtests import _setup
from app.api.schemas.backtests import BacktestIn
from app.backtest.replay import BacktestResult, BacktestSetup, Cancelled, Prices
from app.backtest.store import BacktestStore
from app.core.clock import SystemClock
from app.core.tasks import TaskSupervisor
from app.events.bus import EventBus
from app.services.backtests import (
    BacktestRunningError,
    BacktestService,
    InvalidBacktestError,
    setup_from_json,
    setup_to_json,
)
from tests.api_support import ApiRig, running_api

API = "/api/v1"
DAY = "2023-11-15"


def body(**changes: Any) -> dict[str, Any]:
    setup: dict[str, Any] = {
        "asset": "1HZ75V",
        "first_day": DAY,
        "last_day": DAY,
        "start_time": "10:00",
        "end_time": "10:30",
        "timezone": "UTC",
        "duration_s": 60,
        "mode": "every_candle",
        "max_open_pairs": 3,
        "base_stake": "1.00",
        "strategies": [
            {"strategy": "no_martingale", "max_steps": 0, "multipliers": []},
            {"strategy": "martingale", "max_steps": 3, "multipliers": ["2", "4", "8"]},
            {
                "strategy": "growing_flip",
                "max_steps": 8,
                "multipliers": ["2", "4", "8", "16", "32", "64", "128", "256"],
            },
        ],
    }
    setup.update(changes)
    return setup


async def download(rig: ApiRig, start: str, end: str) -> None:
    started = await rig.client.post(
        f"{API}/prices/downloads", json={"asset": "1HZ75V", "start": start, "end": end}
    )
    assert started.status_code == 202, started.text

    async def done() -> bool:
        return (await rig.client.get(f"{API}/prices")).json()["running"] is None

    await rig.eventually(done)


async def finished(rig: ApiRig, backtest_id: int) -> dict[str, Any]:
    async def done() -> bool:
        found = (await rig.client.get(f"{API}/backtests/{backtest_id}")).json()
        return bool(found["state"] != "running")

    await rig.eventually(done, tries=2000)
    result: dict[str, Any] = (await rig.client.get(f"{API}/backtests/{backtest_id}")).json()
    return result


async def test_a_backtest_compares_the_strategies_on_the_stored_prices(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await download(rig, f"{DAY}T09:50:00Z", f"{DAY}T11:30:00Z")
        response = await rig.client.post(f"{API}/backtests", json=body())
        assert response.status_code == 202, response.text
        started = response.json()
        assert started["state"] == "running" and started["summary"] is None
        assert started["name"] == "1HZ75V 1m, 2023-11-15"
        result = await finished(rig, started["id"])
        assert result["state"] == "done", result["error"]
        assert result["progress"] == 1.0
        summary = result["summary"]
        assert summary["windows"] == 1
        flat, martingale, growing = summary["strategies"]
        assert [s["strategy"] for s in summary["strategies"]] == [
            "no_martingale",
            "martingale",
            "growing_flip",
        ]
        assert flat["pairs"] == 30 and flat["chains"] == 60 and flat["trades"] == 60
        assert sum(flat["won_at_step"]) + flat["exhausted"] == 60
        assert len(growing["won_at_step"]) == 9
        assert martingale["trades"] >= martingale["chains"]
        assert result["setup"]["strategies"][2]["max_steps"] == 8
        assert result["setup"]["payout_pct"] == "88"

        chains = (
            await rig.client.get(f"{API}/backtests/{started['id']}/chains", params={"strategy": 1})
        ).json()
        assert chains["total"] == martingale["chains"]
        first = chains["items"][0]
        assert first["origin"] == "call" and first["pair_no"] == 1
        assert first["started"] == f"{DAY}T10:00:00Z"
        assert first["steps"] == len(first["trades"])
        lost = (
            await rig.client.get(
                f"{API}/backtests/{started['id']}/chains",
                params={"strategy": 0, "status": "exhausted", "limit": 5},
            )
        ).json()
        assert lost["total"] == flat["exhausted"]
        assert all(c["status"] == "exhausted" for c in lost["items"])

        listed = (await rig.client.get(f"{API}/backtests")).json()["items"]
        assert [b["id"] for b in listed] == [started["id"]]
        assert listed[0]["strategies"] == ["no_martingale", "martingale", "growing_flip"]

        assert (await rig.client.delete(f"{API}/backtests/{started['id']}")).status_code == 204
        missing = await rig.client.get(f"{API}/backtests/{started['id']}")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "backtest_not_found"


async def test_a_backtest_needs_stored_prices_and_a_sound_setup(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        no_prices = await rig.client.post(f"{API}/backtests", json=body())
        assert no_prices.status_code == 422
        assert no_prices.json()["error"]["code"] == "invalid_backtest"
        assert "download them first" in no_prices.json()["error"]["message"]

        nine = body(
            strategies=[{"strategy": "growing_flip", "max_steps": 9, "multipliers": ["2"] * 9}]
        )
        assert (await rig.client.post(f"{API}/backtests", json=nine)).status_code == 422
        backwards = body(first_day="2023-11-16", last_day="2023-11-15")
        assert (await rig.client.post(f"{API}/backtests", json=backwards)).status_code == 422
        bad_zone = body(timezone="Mars/Olympus")
        assert (await rig.client.post(f"{API}/backtests", json=bad_zone)).status_code == 422
        steps_without = body(
            strategies=[{"strategy": "no_martingale", "max_steps": 1, "multipliers": ["2"]}]
        )
        assert (await rig.client.post(f"{API}/backtests", json=steps_without)).status_code == 422
        no_window = body(weekdays=[0])  # 2023-11-15 is a Wednesday
        await download(rig, f"{DAY}T09:50:00Z", f"{DAY}T10:40:00Z")
        refused = await rig.client.post(f"{API}/backtests", json=no_window)
        assert refused.json()["error"]["message"] == "No session window falls on the chosen days."


def make_service(tmp_path: Path) -> tuple[BacktestService, BacktestStore, TaskSupervisor]:
    store = BacktestStore(tmp_path / "history.db")
    store.prepare(datetime.now(UTC))
    store.add("1HZ75V", [1_700_042_400], [1.0])
    store.cover("1HZ75V", 1_700_000_000, 1_700_100_000)
    tasks = TaskSupervisor()
    return (
        BacktestService(store=store, bus=EventBus(), tasks=tasks, clock=SystemClock()),
        store,
        tasks,
    )


async def test_one_backtest_at_a_time_and_cancel(tmp_path: Path) -> None:
    service, _store, tasks = make_service(tmp_path)
    entered = threading.Event()

    def slow(
        prices: Prices, setup: BacktestSetup, *, progress: Any, cancel: threading.Event
    ) -> BacktestResult:
        entered.set()
        cancel.wait(10)
        raise Cancelled

    setup = _setup(BacktestIn.model_validate(body()))
    with patch("app.services.backtests.replay", slow):
        row = await service.start(setup)
        with pytest.raises(BacktestRunningError):
            await service.start(setup)
        with pytest.raises(BacktestRunningError):
            await service.delete(row.id)
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        cancelled = await service.cancel(row.id)
    assert cancelled.state == "cancelled"
    assert service.running is None
    with pytest.raises(InvalidBacktestError, match="At most 92 days"):
        await service.start(replace(setup, last_day=setup.first_day + timedelta(days=92)))
    await tasks.shutdown()


def test_a_backtest_cut_by_a_stop_is_marked_failed_and_the_setup_round_trips(
    tmp_path: Path,
) -> None:
    setup = _setup(BacktestIn.model_validate(body(profit_target="5.00", pause_s=30)))
    assert setup_from_json(setup_to_json(setup)) == setup
    store = BacktestStore(tmp_path / "history.db")
    store.prepare(datetime.now(UTC))
    row = store.new_backtest("x", "{}", datetime.now(UTC))
    assert BacktestStore(store.path).prepare(datetime.now(UTC)) == 1
    found = store.backtest(row.id)
    assert found is not None
    assert (found.state, found.error) == ("failed", "The program stopped during the backtest.")


async def test_trend_sessions_run_beside_always_on_ones_on_two_periods(tmp_path: Path) -> None:
    """Phase 31: each strategy opened all through the window and after breakouts, on a first
    period and on a second one that judges it; the Market page reads where the pairs opened."""
    async with running_api(tmp_path) as rig:
        await download(rig, f"{DAY}T07:50:00Z", f"{DAY}T11:30:00Z")
        trend = body(
            strategies=[{"strategy": "martingale", "max_steps": 2, "multipliers": ["2", "4"]}],
            opens=["window", "breakout"],
            market={"pattern": "alternating", "candles": 3, "breakout_candles": 1},
            trend_max_candles=10,
            check_first_day=DAY,
            check_last_day=DAY,
        )
        response = await rig.client.post(f"{API}/backtests", json=trend)
        assert response.status_code == 202, response.text
        result = await finished(rig, response.json()["id"])
        assert result["state"] == "done", result["error"]
        runs = result["summary"]["strategies"]
        assert [(r["opens"], r["period"], r["index"]) for r in runs] == [
            ("window", 1, 0),
            ("breakout", 1, 0),
            ("window", 2, 0),
            ("breakout", 2, 0),
        ]
        always, after = runs[0], runs[1]
        assert always["spans"] == 1 and always["active_s"] == 1800
        assert after["active_s"] <= 1800 and after["pairs"] <= always["pairs"]
        assert result["setup"]["opens"] == ["window", "breakout"]
        assert result["setup"]["check_first_day"] == DAY

        pairs = (
            await rig.client.get(f"{API}/backtests/{result['id']}/pairs", params={"run": 1})
        ).json()
        assert pairs["total"] == after["pairs"]
        assert [p["at"] for p in pairs["items"]] == sorted(p["at"] for p in pairs["items"])
        chains = (
            await rig.client.get(
                f"{API}/backtests/{result['id']}/chains", params={"strategy": 1, "limit": 200}
            )
        ).json()
        assert chains["total"] == after["chains"]

        half = body(check_first_day=DAY)
        assert (await rig.client.post(f"{API}/backtests", json=half)).status_code == 422
        four = [
            *body()["strategies"],
            {"strategy": "flip_every_loss", "max_steps": 1, "multipliers": ["2"]},
        ]
        too_many = body(
            strategies=four, opens=["window", "breakout"], check_first_day=DAY, check_last_day=DAY
        )  # 4 strategies x 2 ways x 2 periods: 16 runs
        alone = await rig.client.post(f"{API}/backtests", json=body(strategies=four))
        assert alone.status_code == 202  # the four strategies are fine on their own
        await finished(rig, alone.json()["id"])
        assert (await rig.client.post(f"{API}/backtests", json=too_many)).status_code == 422
        bad_rules = body(opens=["breakout"], market={"pattern": "mixed", "candles": 4, "misses": 3})
        refused = await rig.client.post(f"{API}/backtests", json=bad_rules)
        assert refused.status_code == 422
        twice = body(opens=["window", "window"])
        assert (await rig.client.post(f"{API}/backtests", json=twice)).status_code == 422
