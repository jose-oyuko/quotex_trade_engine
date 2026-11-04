"""The `api:watch` script: what it prints for the frames a dashboard would receive."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from websockets.exceptions import WebSocketException

from scripts.ws_watch import describe, login_cookie, watch
from tests.api_support import OWNER_NAME, OWNER_PASSWORD, running_api, serve


def test_a_snapshot_is_summarised() -> None:
    line = describe(
        {
            "type": "snapshot",
            "seq": 7,
            "reason": "connect",
            "data": {
                "account_type": "demo",
                "open_chains": [{}, {}],
                "open_trades": [{}],
                "connections": {"telegram": {}, "quotex": {}},
            },
        }
    )
    assert line == (
        "#7 snapshot reason=connect account=demo open_chains=2 open_trades=1 "
        "connections=['quotex', 'telegram']"
    )


def test_an_event_shows_the_fields_that_matter() -> None:
    data = {"asset": "EURUSD", "status": "won", "step": 1, "stake": "2.00", "profit": "1.70"}
    line = describe({"type": "trade.settled", "seq": 12, "data": data})
    assert line == "#12 trade.settled asset=EURUSD status=won step=1 stake=2.00 profit=1.70"


def test_a_heartbeat_is_just_its_number() -> None:
    assert describe({"type": "heartbeat", "seq": 3}) == "#3 heartbeat"


def test_odd_frames_do_not_crash_it() -> None:
    assert describe({"type": "snapshot", "seq": 1, "data": {"connections": 5}}).startswith("#1")
    assert describe({}) == "#None None"


async def test_it_prints_what_a_real_server_sends(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    async with running_api(tmp_path, ws_heartbeat_s=0.05) as rig, serve(rig.app) as address:
        with pytest.raises(TimeoutError):
            # connecting alone takes up to half a second on a slow PC; heartbeats come every 50 ms
            await asyncio.wait_for(watch(f"ws://{address}/ws", rig.ws_headers()["Cookie"]), 2.0)
    # the application's own log lines may share stdout (depending on which tests ran before)
    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(("connected to", "#"))
    ]
    assert lines[0] == f"connected to ws://{address}/ws"
    assert lines[1].startswith("#0 snapshot reason=connect account=demo")
    assert "#0 heartbeat" in lines


async def test_it_logs_in_like_the_dashboard_and_the_feed_refuses_it_without(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, logged_in=False) as rig, serve(rig.app) as address:
        await rig.app.state.auth.set_owner(username=OWNER_NAME, password=OWNER_PASSWORD)
        with pytest.raises(WebSocketException):
            await asyncio.wait_for(watch(f"ws://{address}/ws"), 2)
        cookie = await login_cookie(f"ws://{address}/ws", OWNER_NAME, OWNER_PASSWORD)
        assert cookie.startswith("qte_session=")
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(watch(f"ws://{address}/ws", cookie), 0.3)
