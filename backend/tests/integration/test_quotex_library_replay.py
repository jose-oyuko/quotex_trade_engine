"""The real pyquotex library, our wrapper and the adapter, against a local fake Quotex websocket.

Everything here runs offline and without credentials. See tests/quotex_replay_server.py for what
this does and does not prove.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.clock import SystemClock
from app.core.tasks import TaskSupervisor
from app.domain.enums import AccountType, Direction
from app.quotex import PyQuotexAdapter
from app.quotex.backoff import BackoffPolicy
from app.quotex.base import ConnectionState, TradeOutcome
from app.quotex.errors import (
    OrderAckTimeoutError,
    QuotexConnectionError,
    ResultTimeoutError,
)
from app.quotex.pyquotex_client import PyQuotexClient
from tests.quotex_replay_server import ReplayQuotexServer
from tests.quotex_support import make_row

D = Decimal
EMAIL = "tester@example.invalid"


@dataclass
class Env:
    server: ReplayQuotexServer
    url: str
    data_dir: Path
    tasks: TaskSupervisor

    def client(self) -> PyQuotexClient:
        return PyQuotexClient(
            email=EMAIL,
            password="not-a-real-password",
            host="127.0.0.1",
            data_dir=self.data_dir,
            wss_url_override=self.url,
        )

    def adapter(self, **kwargs: object) -> PyQuotexAdapter:
        return PyQuotexAdapter(
            self.client,
            tasks=self.tasks,
            clock=SystemClock(),
            backoff=BackoffPolicy(base_s=0.05, cap_s=0.2, jitter=0.0),
            ack_timeout_s=0.5,
            monitor_interval_s=0.02,
            **kwargs,  # type: ignore[arg-type]
        )

    def stored_session(self) -> dict[str, object]:
        return json.loads((self.data_dir / "session.json").read_text())[EMAIL]  # type: ignore[no-any-return]


@pytest.fixture
async def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Env]:
    # Run from an unrelated folder: anything the library writes "next to us" would show up there.
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # A stored session, so the library skips the HTTP login and goes straight to the websocket.
    (data_dir / "session.json").write_text(
        json.dumps({EMAIL: {"cookies": "a=b", "token": "stored-token", "user_agent": "test-agent"}})
    )

    server = ReplayQuotexServer(
        rows=[
            make_row("EURUSD", payout_1m=86, payout_5m=82),
            make_row("GBPUSD_otc", payout_1m=90, payout_5m=88),
            make_row("AUDUSD", is_open=False),
        ]
    )
    url = await server.start()
    tasks = TaskSupervisor()
    yield Env(server, url, data_dir, tasks)
    await tasks.shutdown()
    await server.stop()


# ---- the wrapper against the real library ------------------------------------------------------


async def test_connect_and_warm_up_fill_the_in_memory_state(env: Env) -> None:
    client = env.client()
    await client.connect(demo=True)
    try:
        await client.warm_up()  # the profile download fails offline; that must not break warm-up
        assert client.is_connected()
        assert client.active_account_is_demo() is True
        assert client.balance_payload() == {"demoBalance": 10000.5, "liveBalance": 25.0}
        assert [row[1] for row in client.instruments()] == ["EURUSD", "GBPUSD_otc", "AUDUSD"]
    finally:
        await client.close()
    assert not client.is_connected()


async def test_the_library_does_not_write_into_the_working_directory(env: Env) -> None:
    client = env.client()
    await client.connect(demo=True)
    await client.close()
    assert list(Path.cwd().iterdir()) == []  # nothing next to the process
    assert env.stored_session()["token"] == "stored-token"


async def test_the_stored_token_is_sent_to_the_server_to_authorise(env: Env) -> None:
    client = env.client()
    await client.connect(demo=True)
    await client.close()
    [auth, *_] = env.server.events("authorization")
    assert auth == {"session": "stored-token", "isDemo": 1, "tournamentId": 0}


async def test_a_rejected_session_fails_and_forgets_the_stored_token(env: Env) -> None:
    env.server.reject_auth = True
    client = env.client()
    with pytest.raises(QuotexConnectionError, match="rejected"):
        await client.connect(demo=True)
    await client.close()
    assert env.stored_session()["token"] is None  # next attempt logs in again instead of looping


# ---- the adapter on top ------------------------------------------------------------------------


async def test_full_round_trip_through_the_adapter(env: Env) -> None:
    adapter = env.adapter()
    await adapter.connect()
    try:
        assert adapter.state is ConnectionState.CONNECTED
        assert adapter.payout("EURUSD", 1) == 86
        assert adapter.payout("EURUSD", 5) == 82
        assert adapter.is_open("GBPUSD_otc") and not adapter.is_open("AUDUSD")
        balance = adapter.balance()
        assert balance is not None and balance.balance == D("10000.50")

        ack = await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.50"))
        assert ack.order_id == "srv-1"
        result = await adapter.await_result(ack.order_id, 2)
        assert (result.outcome, result.profit) == (TradeOutcome.WON, D("0.85"))
    finally:
        await adapter.disconnect()

    # What actually went over the wire:
    [order] = env.server.events("orders/open")
    assert order["asset"] == "EURUSD"
    assert order["amount"] == 1.5
    assert order["action"] == "call"
    assert order["isDemo"] == 1  # demo account
    assert order["optionType"] == 3  # TIME mode
    assert env.server.events("depth/follow") == ["EURUSD"]  # price subscription made once


async def test_a_losing_result_arrives_as_a_negative_profit(env: Env) -> None:
    env.server.profits.append(-1.5)
    adapter = env.adapter()
    await adapter.connect()
    try:
        ack = await adapter.place_order("EURUSD", Direction.PUT, 60, D("1.50"))
        result = await adapter.await_result(ack.order_id, 2)
        assert (result.outcome, result.profit) == (TradeOutcome.LOST, D("-1.50"))
    finally:
        await adapter.disconnect()


async def test_several_orders_in_a_row_each_get_their_own_confirmation(env: Env) -> None:
    adapter = env.adapter()
    await adapter.connect()
    try:
        acks = await asyncio.gather(
            *(adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00")) for _ in range(5))
        )
        assert sorted(a.order_id for a in acks) == [f"srv-{n}" for n in range(1, 6)]
        results = [await adapter.await_result(a.order_id, 2) for a in acks]
        assert all(r.outcome is TradeOutcome.WON for r in results)
    finally:
        await adapter.disconnect()


async def test_switching_account_is_sent_and_orders_follow_it(env: Env) -> None:
    adapter = env.adapter(allow_real=True)
    await adapter.connect()
    try:
        await adapter.set_account_type(AccountType.REAL)
        await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    finally:
        await adapter.disconnect()
    assert {"demo": 0, "tournamentId": 0} in env.server.events("account/change")
    assert env.server.events("orders/open")[0]["isDemo"] == 0


async def test_a_missing_order_confirmation_times_out_as_possibly_placed(env: Env) -> None:
    env.server.send_order_ack = False
    adapter = env.adapter()
    await adapter.connect()
    try:
        with pytest.raises(OrderAckTimeoutError):
            await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
        assert len(env.server.events("orders/open")) == 1  # it really was sent
    finally:
        await adapter.disconnect()


async def test_an_unsettled_order_times_out_instead_of_reporting_a_loss(env: Env) -> None:
    env.server.settle_after_s = None
    adapter = env.adapter()
    await adapter.connect()
    try:
        ack = await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
        with pytest.raises(ResultTimeoutError):
            await adapter.await_result(ack.order_id, 0.1)
    finally:
        await adapter.disconnect()


async def test_no_price_ticks_means_the_first_order_is_refused_cleanly(env: Env) -> None:
    env.server.send_ticks = False
    adapter = env.adapter()
    await adapter.connect()
    try:
        with pytest.raises(QuotexConnectionError, match="no price ticks"):
            await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
        assert env.server.events("orders/open") == []
    finally:
        await adapter.disconnect()


async def test_a_dropped_websocket_is_noticed_and_re_established(env: Env) -> None:
    adapter = env.adapter()
    await adapter.connect()
    try:
        await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
        assert env.server.connections == 1

        await env.server.drop_clients()
        async with asyncio.timeout(5):
            while env.server.connections < 2 or adapter.state is not ConnectionState.CONNECTED:  # noqa: ASYNC110
                await asyncio.sleep(0.02)

        ack = await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
        assert ack.order_id
        assert len(env.server.events("orders/open")) == 2
        assert len(env.server.events("depth/follow")) == 2  # fresh connection, fresh subscription
    finally:
        await adapter.disconnect()


async def test_place_order_overhead_on_loopback_is_small(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    """Measures the adapter + library cost of an order when the 'network' is free (the server
    answers at once). Printed, and bounded generously so only a real regression fails it."""
    adapter = env.adapter()
    await adapter.connect()
    try:
        await adapter.prepare_asset("EURUSD", 60)
        timings_ms = []
        for _ in range(20):
            ack = await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
            timings_ms.append((ack.t_order_acked_ns - ack.t_order_sent_ns) / 1e6)
    finally:
        await adapter.disconnect()
    timings_ms.sort()
    with capsys.disabled():
        print(
            f"\n[benchmark] place_order send->ack on loopback, 20 orders: "
            f"median {timings_ms[10]:.1f} ms, max {timings_ms[-1]:.1f} ms"
        )
    assert timings_ms[10] < 50  # the old Quotex.buy() path adds >= 200 ms of polling on top
