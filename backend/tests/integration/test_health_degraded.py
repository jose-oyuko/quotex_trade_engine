"""/health says when something is wrong, in words the owner can act on."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api_support import running_api

HEALTH = "/api/v1/health"


async def health(rig: Any) -> dict[str, Any]:
    body: dict[str, Any] = (await rig.client.get(HEALTH)).json()
    return body


async def test_a_healthy_application_has_no_problems(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        body = await health(rig)
    assert body["status"] == "ok" and body["problems"] == []
    assert body["writer"]["retrying"] is False


async def test_a_healthy_engine_with_both_connections_has_no_problems(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:

        async def settled() -> bool:
            return (await health(rig))["telegram"] is not None

        await rig.eventually(settled)
        body = await health(rig)
    assert body["status"] == "ok" and body["problems"] == []


async def test_a_lost_quotex_connection_is_reported_and_clears_when_it_returns(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        adapter = rig.fakes.adapter
        adapter.simulate_connection_loss()

        async def reported() -> bool:
            return any("Quotex is not connected" in p for p in (await health(rig))["problems"])

        await rig.eventually(reported)
        body = await health(rig)
        assert body["status"] == "degraded"
        assert body["quotex"]["connected"] is False

        adapter.simulate_connection_restored()

        async def cleared() -> bool:
            return (await health(rig))["status"] == "ok"

        await rig.eventually(cleared)


async def test_a_lost_telegram_connection_is_reported(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        rig.fakes.engine.listener._announce(False, "connection lost")
        await rig.eventually(_reports(rig, "Telegram is not connected"))
        assert (await health(rig))["status"] == "degraded"


def _reports(rig: Any, fragment: str):  # type: ignore[no-untyped-def]
    async def check() -> bool:
        return any(fragment in p for p in (await health(rig))["problems"])

    return check


async def test_an_unreachable_database_is_reported(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        engine: AsyncEngine = rig.app.state.engine
        await engine.dispose()
        rig.app.state.engine = None  # nothing to connect with
        body = await health(rig)
        assert body["status"] == "degraded" and body["database"] == "unavailable"
        assert "cannot be reached" in body["problems"][0]
        rig.app.state.engine = engine  # so shutdown can dispose it normally


async def test_a_writer_that_is_waiting_for_the_database_is_reported(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        rig.app.state.writer.retrying = True
        body = await health(rig)
        assert body["status"] == "degraded" and body["writer"]["retrying"] is True
        assert "not accepting writes" in body["problems"][0]
        rig.app.state.writer.retrying = False


async def test_lost_history_is_reported_so_it_is_never_silent(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        writer = rig.app.state.writer
        writer.stats.failed = 2
        writer._subscription.dropped = 7
        body = await health(rig)
    assert body["status"] == "degraded"
    assert any("7 events were dropped" in p for p in body["problems"])
    assert any("2 records could not be stored" in p for p in body["problems"])
