"""Crash and restart, end to end: the real application, a real database file, started twice.

A crash is simulated by never running the application's shutdown: its tasks are cancelled and its
database connection is closed without the writer flushing, exactly the state a killed process leaves
behind. The second start must find the truth in the database and say what it could not know.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from app.engine.manager import RESTART_REASON
from app.main import create_app
from app.quotex.base import TradeOutcome
from tests.api_support import (
    BASE_URL,
    ApiRig,
    FakeParts,
    fake_builder,
    migrate,
    running_api,
    settings_for,
)

API = "/api/v1"


async def wait_stored(rig: ApiRig, path: str, check: Any) -> dict[str, Any]:
    """Poll the API until the database shows what is expected (the writer is a moment behind)."""
    last: dict[str, Any] = {}

    async def ready() -> bool:
        nonlocal last
        last = (await rig.client.get(f"{API}{path}")).json()
        return bool(check(last))

    await rig.eventually(ready)
    return last


async def crash(app: FastAPI, lifespan: AbstractAsyncContextManager[None]) -> None:
    """Stop the application the way a power cut would: no shutdown, no flush."""
    await app.state.tasks.shutdown(grace_seconds=0.1)  # the writer is cancelled, not drained
    await app.state.engine.dispose()
    # The shutdown code is never run. Closing the generator only silences Python's complaint about
    # an abandoned one at the end of the test.
    with contextlib.suppress(RuntimeError, GeneratorExit):
        await lifespan.gen.aclose()  # type: ignore[attr-defined]


async def test_a_hard_crash_leaves_work_in_flight_and_the_restart_flags_it_unknown(
    tmp_path: Path,
) -> None:
    # --- first life: a trade is open (its result is held back), limits and a pause are set ---
    config = settings_for(tmp_path, engine_enabled=True)
    await migrate(config)
    parts: list[FakeParts] = []
    app = create_app(config, engine_builder=fake_builder(parts, hold_results=True))
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)
    rig = ApiRig(app, client, config, parts)
    assert await parts[0].engine.listener.wait_until_connected(2)

    await rig.create_group()
    await rig.create_group(
        telegram_chat_id=-1002,
        title="Other",
        settings={"strategy": "no_martingale", "max_steps": 0, "multipliers": []},
    )
    await client.put(f"{API}/risk/limits", json={"daily_stop_loss": "50.00", "max_stake": "20.00"})
    await client.post(f"{API}/groups/2/pause")
    parts[0].adapter.script_results(TradeOutcome.LOST)
    parts[0].signal(-1001, "EURUSD CALL 1m")
    await wait_stored(rig, "/trades?status=open", lambda body: body["total"] == 1)
    await wait_stored(rig, "/chains?status=open", lambda body: body["total"] == 1)

    await client.aclose()
    await crash(app, lifespan)

    # --- second life: the same database ---
    async with running_api(tmp_path, with_engine=True) as again:
        summary = (await again.client.get(f"{API}/status")).json()
        # nothing is trusted to be running: the chain and its trade are marked unknown, loudly
        chains = await wait_stored(
            again, "/chains", lambda body: body["items"][0]["status"] == "unknown"
        )
        assert chains["items"][0]["end_reason"] == RESTART_REASON
        trades = await wait_stored(
            again, "/trades", lambda body: body["items"][0]["status"] == "unknown"
        )
        assert trades["items"][0]["error"] == RESTART_REASON
        assert summary["open_chains"] == [] and summary["open_trades"] == []

        async def risk_event_listed() -> bool:
            events = (await again.client.get(f"{API}/risk/events")).json()["items"]
            return any(e["kind"] == "restart_unknown" for e in events)

        await again.eventually(risk_event_listed)

        # the owner's settings survived: limits, the pause
        risk = (await again.client.get(f"{API}/risk")).json()["controls"]
        assert (
            risk["limits"]["daily_stop_loss"] == "50.00" and risk["limits"]["max_stake"] == "20.00"
        )
        assert risk["paused_groups"] == [2]
        groups = {g["id"]: g for g in (await again.client.get(f"{API}/groups")).json()["items"]}
        assert groups[2]["paused"] is True and groups[1]["paused"] is False

        # and trading works again: the group that had a chain in flight is not stuck
        again.fakes.signal(-1001, "GBPUSD CALL 1m")
        await wait_stored(again, "/trades", lambda body: body["total"] == 2)
        assert len(again.fakes.adapter.orders) == 1


async def test_the_kill_switch_and_the_days_loss_survive_a_crash(tmp_path: Path) -> None:
    config = settings_for(tmp_path, engine_enabled=True)
    await migrate(config)
    parts: list[FakeParts] = []
    app = create_app(config, engine_builder=fake_builder(parts))  # results arrive at once
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)
    rig = ApiRig(app, client, config, parts)
    assert await parts[0].engine.listener.wait_until_connected(2)

    await rig.create_group(
        settings={"strategy": "no_martingale", "max_steps": 0, "multipliers": []}
    )
    await client.put(f"{API}/risk/limits", json={"daily_stop_loss": "1.00"})
    parts[0].adapter.script_results(TradeOutcome.LOST)
    parts[0].signal(-1001, "EURUSD CALL 1m")  # a lost 1.00 trade: the stop-loss is reached
    await wait_stored(rig, "/trades?status=lost", lambda body: body["total"] == 1)
    assert (await client.post(f"{API}/kill-switch")).status_code == 200
    await rig.eventually(_setting_stored(tmp_path))
    await client.aclose()
    await crash(app, lifespan)

    async with running_api(tmp_path, with_engine=True) as again:
        controls = (await again.client.get(f"{API}/risk")).json()
        assert controls["controls"]["kill_switch"] is True  # still engaged after the crash
        assert controls["day"]["pnl"].startswith(
            "-"
        )  # and today's loss was rebuilt from the trades
        await again.client.delete(f"{API}/kill-switch")
        again.fakes.signal(-1001, "GBPUSD CALL 1m")  # the stop-loss alone still blocks it

        async def blocked() -> bool:
            events = (await again.client.get(f"{API}/risk/events")).json()["items"]
            return any(e["kind"] == "daily_stop_loss" for e in events)

        await again.eventually(blocked)
        assert again.fakes.adapter.orders == []


def _setting_stored(tmp_path: Path):  # type: ignore[no-untyped-def]
    """True once the kill switch has reached the database file (so the crash cannot lose it)."""
    import sqlite3

    async def check() -> bool:
        db = sqlite3.connect(tmp_path / "data" / "quotex.db")
        try:
            rows = db.execute(
                "SELECT value FROM app_settings WHERE key='controls.kill_switch'"
            ).fetchall()
        finally:
            db.close()
        return bool(rows) and "true" in str(rows[0][0]).lower()

    return check


async def test_a_graceful_shutdown_is_quick_and_flushes_everything_it_knew(tmp_path: Path) -> None:
    started = time.perf_counter()
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        await rig.create_group()
        rig.fakes.signal(-1001, "EURUSD CALL 1m")
        await rig.eventually(_orders(rig, 1))
        # change something at the very last moment: it must still reach the database
        await rig.client.post(f"{API}/groups/1/pause")
        await rig.client.put(f"{API}/risk/limits", json={"max_stake": "7.00"})
        left = time.perf_counter()
    shutdown_s = time.perf_counter() - left
    assert shutdown_s < 3.0, f"shutdown took {shutdown_s:.1f}s with a trade open"
    assert time.perf_counter() - started < 15

    async with running_api(tmp_path) as again:  # engine off: just read what was stored
        risk = (await again.client.get(f"{API}/risk")).json()["controls"]
        assert risk["limits"]["max_stake"] == "7.00" and risk["paused_groups"] == [1]
        chain = (await again.client.get(f"{API}/chains")).json()["items"][0]
        # the application was stopped while the trade was open: stored as it was, flagged next start
        assert chain["status"] in ("open", "pending")


def _orders(rig: ApiRig, count: int):  # type: ignore[no-untyped-def]
    async def check() -> bool:
        await asyncio.sleep(0)
        return len(rig.fakes.adapter.orders) >= count

    return check


async def test_a_second_start_after_a_graceful_stop_also_flags_what_was_open(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True, hold_results=True) as rig:
        await rig.create_group()
        rig.fakes.signal(-1001, "EURUSD CALL 1m")
        await rig.eventually(_orders(rig, 1))

        async def stored() -> bool:
            return (await rig.client.get(f"{API}/trades?status=open")).json()["total"] == 1

        await rig.eventually(stored)
    async with running_api(tmp_path, with_engine=True) as again:
        trades = await wait_stored(
            again, "/trades", lambda body: body["items"][0]["status"] == "unknown"
        )
        assert trades["items"][0]["error"] == RESTART_REASON
        health = (await again.client.get(f"{API}/health")).json()
        assert health["writer"]["failed"] == 0
