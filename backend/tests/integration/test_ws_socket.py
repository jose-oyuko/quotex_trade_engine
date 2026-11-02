"""/ws over a real socket: the protocol as a dashboard sees it."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.api.schemas.ws import ServerMessage
from tests.api_support import running_api, serve

SERVER_MESSAGE: TypeAdapter[Any] = TypeAdapter(ServerMessage)


async def recv(ws: ClientConnection, within: float = 5.0) -> dict[str, Any]:
    """The next frame, checked against the published protocol (a drifting message fails here)."""
    raw = await asyncio.wait_for(ws.recv(), within)
    SERVER_MESSAGE.validate_json(raw)
    message: dict[str, Any] = json.loads(raw)
    return message


async def recv_until(
    ws: ClientConnection, done: Callable[[dict[str, Any]], bool]
) -> list[dict[str, Any]]:
    got: list[dict[str, Any]] = []
    while True:
        message = await recv(ws)
        got.append(message)
        if done(message):
            return got


async def test_a_dashboard_gets_a_snapshot_then_the_events_in_order(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig, serve(rig.app) as address:
        await rig.create_group()
        async with connect(f"ws://{address}/ws") as ws:
            snapshot = await recv(ws)
            assert snapshot["type"] == "snapshot" and snapshot["reason"] == "connect"
            assert snapshot["data"]["engine"] == {"enabled": True, "running": True}
            assert snapshot["data"]["account_type"] == "demo"

            rig.fakes.signal(-1001, "EURUSD CALL 1m")
            events = await recv_until(ws, lambda m: m["type"] == "chain.ended")
            seqs = [m["seq"] for m in events if m["type"] != "heartbeat"]
            assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))  # consecutive: nothing missed
            assert seqs[0] > snapshot["seq"] or seqs[0] == snapshot["seq"] + 1
            types = [m["type"] for m in events if m["type"] != "heartbeat"]
            assert types.index("signal.received") < types.index("chain.started")
            assert types.index("chain.started") < types.index("trade.opened")
            assert types.index("trade.opened") < types.index("trade.settled")
            assert types.index("trade.settled") < types.index("chain.ended")
            settled = next(m for m in events if m["type"] == "trade.settled")
            assert settled["data"]["status"] == "won" and settled["data"]["asset"] == "EURUSD"
            ended = events[-1]
            assert ended["data"]["status"] == "completed"


async def test_a_dashboard_that_connects_later_sees_the_chain_that_is_already_running(
    tmp_path: Path,
) -> None:
    async with (
        running_api(tmp_path, with_engine=True, hold_results=True) as rig,
        serve(rig.app) as address,
    ):
        await rig.create_group()
        rig.fakes.signal(-1001, "EURUSD CALL 1m")

        async def running() -> bool:
            return (await rig.client.get("/api/v1/status")).json()["open_trades"] != []

        await rig.eventually(running)
        async with connect(f"ws://{address}/ws") as ws:
            snapshot = await recv(ws)
            [chain] = snapshot["data"]["open_chains"]
            [trade] = snapshot["data"]["open_trades"]
            assert chain["asset"] == "EURUSD" and trade["status"] == "open"
            rig.fakes.adapter.settle_all()
            after = await recv_until(ws, lambda m: m["type"] == "chain.ended")
            assert after[0]["seq"] == snapshot["seq"] + 1  # picks up exactly where it left off


async def test_asking_for_a_resync_gets_a_fresh_snapshot(tmp_path: Path) -> None:
    async with (
        running_api(tmp_path, with_engine=True) as rig,
        serve(rig.app) as address,
        connect(f"ws://{address}/ws") as ws,
    ):
        first = await recv(ws)
        await ws.send(json.dumps({"type": "resync"}))
        again = await recv_until(ws, lambda m: m["type"] == "snapshot")
        assert again[-1]["reason"] == "resync"
        assert again[-1]["seq"] >= first["seq"]


async def test_two_dashboards_see_the_same_numbers(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig, serve(rig.app) as address:
        await rig.create_group()
        async with connect(f"ws://{address}/ws") as one, connect(f"ws://{address}/ws") as two:
            await recv(one), await recv(two)
            rig.fakes.signal(-1001, "EURUSD CALL 1m")
            a = await recv_until(one, lambda m: m["type"] == "chain.ended")
            b = await recv_until(two, lambda m: m["type"] == "chain.ended")
            assert [(m["seq"], m["type"]) for m in a] == [(m["seq"], m["type"]) for m in b]


async def test_a_quiet_connection_gets_heartbeats(tmp_path: Path) -> None:
    async with (
        running_api(tmp_path, ws_heartbeat_s=0.1) as rig,
        serve(rig.app) as address,
        connect(f"ws://{address}/ws") as ws,
    ):
        snapshot = await recv(ws)
        beat = await recv(ws)
        assert beat["type"] == "heartbeat" and beat["seq"] == snapshot["seq"]


async def test_changes_made_through_the_api_reach_the_dashboard(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig, serve(rig.app) as address:
        await rig.create_group()
        async with connect(f"ws://{address}/ws") as ws:
            await recv(ws)
            assert (await rig.client.post("/api/v1/kill-switch")).status_code == 200
            changed = await recv_until(ws, lambda m: m["type"] == "controls.changed")
            assert changed[-1]["data"]["kill_switch"] is True
            await rig.client.post("/api/v1/groups/1/pause")
            paused = await recv_until(ws, lambda m: m["type"] == "controls.changed")
            assert paused[-1]["data"]["paused_groups"] == [1]
            await rig.client.put("/api/v1/risk/limits", json={"max_stake": "7.00"})
            limits = await recv_until(ws, lambda m: m["type"] == "controls.changed")
            assert limits[-1]["data"]["limits"]["max_stake"] == "7.00"


async def test_nonsense_from_a_client_is_ignored_and_a_huge_message_ends_the_connection(
    tmp_path: Path,
) -> None:
    async with (
        running_api(tmp_path) as rig,
        serve(rig.app) as address,
        connect(f"ws://{address}/ws") as ws,
    ):
        await recv(ws)
        for junk in ("not json", '{"type": "shout"}', "[]", '{"type": 5}'):
            await ws.send(junk)
        await ws.send(json.dumps({"type": "resync"}))
        assert (await recv_until(ws, lambda m: m["type"] == "snapshot"))[-1]["reason"] == "resync"
        await ws.send("x" * 5000)
        with pytest.raises(ConnectionClosed) as closed:
            while True:
                await asyncio.wait_for(ws.recv(), 5)
        assert closed.value.rcvd is not None and closed.value.rcvd.code == 1009


async def test_a_closed_connection_is_forgotten(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig, serve(rig.app) as address:
        async with connect(f"ws://{address}/ws") as ws:
            await recv(ws)
            assert rig.app.state.hub.clients == 1
        await _until(lambda: rig.app.state.hub.clients == 0)
        health = (await rig.client.get("/api/v1/health")).json()
        assert health["ws_clients"] == 0


async def test_pages_from_other_sites_and_other_host_names_cannot_connect(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig, serve(rig.app) as address:
        with pytest.raises(InvalidStatus) as hostile:
            async with connect(f"ws://{address}/ws", origin="http://evil.example"):
                pass
        assert hostile.value.response.status_code == 403
        with pytest.raises(InvalidStatus) as rebinding:
            async with connect(f"ws://{address}/ws", additional_headers={"Host": "evil.example"}):
                pass
        assert rebinding.value.response.status_code == 403
        # the dashboard's own origin (same host:port) and the dev server's are fine
        async with connect(f"ws://{address}/ws", origin=f"http://{address}") as ws:
            assert (await recv(ws))["type"] == "snapshot"
        async with connect(f"ws://{address}/ws", origin="http://127.0.0.1:5173") as ws:
            assert (await recv(ws))["type"] == "snapshot"


async def test_a_dashboard_that_reads_too_slowly_loses_events_not_the_engine(
    tmp_path: Path,
) -> None:
    """A real socket that is not being read: the engine and a second dashboard carry on."""
    async with (
        running_api(tmp_path, with_engine=True, ws_client_queue=3) as rig,
        serve(rig.app) as address,
    ):
        await rig.create_group(
            settings={"strategy": "no_martingale", "max_steps": 0, "multipliers": []}
        )
        async with connect(f"ws://{address}/ws") as lazy, connect(f"ws://{address}/ws") as busy:
            await recv(lazy), await recv(busy)
            for asset in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD"):
                rig.fakes.signal(-1001, f"{asset} CALL 1m")
            await rig.fakes.engine.manager.wait_idle(5)  # the engine was not held up
            assert len(rig.fakes.adapter.orders) == 4
            hub = rig.app.state.hub
            assert hub.stats.messages >= 16
            # the lazy dashboard's bounded queue overflowed; it is told to start over, and the
            # frame it gets is a snapshot that already includes everything that happened
            frame = await recv(lazy)
            seen = [frame]
            while not (frame["type"] == "snapshot" and frame["reason"] == "slow_consumer"):
                frame = await recv(lazy)
                seen.append(frame)
            assert frame["seq"] == max(m["seq"] for m in seen)
            assert hub.stats.resyncs >= 1


async def _until(check: Callable[[], bool], tries: int = 400) -> None:
    for _ in range(tries):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached in time")
