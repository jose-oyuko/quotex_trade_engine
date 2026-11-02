"""Behaviour specific to the real adapter's logic: reconnect, backoff, timeouts, safety.
(Behaviour shared with the fake is in tests/contract/.)"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.core.backoff import BackoffPolicy
from app.core.clock import SystemClock
from app.core.tasks import TaskSupervisor
from app.domain.enums import AccountType, Direction
from app.events.bus import EventBus
from app.events.types import BalanceUpdated, ConnectionChanged
from app.quotex import PyQuotexAdapter
from app.quotex.base import ConnectionState
from app.quotex.errors import (
    OrderRejectedError,
    PayoutSanityError,
    QuotexConnectionError,
)
from tests.quotex_support import ScriptedClient, World, make_row

D = Decimal


class Sleeps:
    """Stands in for asyncio.sleep in backoff waits: records the delays, waits for nothing."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        await asyncio.sleep(0)


def build(
    world: World, **kwargs: object
) -> tuple[PyQuotexAdapter, EventBus, Sleeps, TaskSupervisor]:
    bus, sleeps, tasks = EventBus(), Sleeps(), TaskSupervisor()
    adapter = PyQuotexAdapter(
        lambda: ScriptedClient(world),
        tasks=tasks,
        clock=SystemClock(),
        bus=bus,
        backoff=BackoffPolicy(base_s=1, cap_s=30, jitter=0.1),
        sleep=sleeps,
        rng=lambda: 0.5,  # no jitter: delay * (1 + 0)
        monitor_interval_s=0.005,
        **kwargs,  # type: ignore[arg-type]
    )
    return adapter, bus, sleeps, tasks


@pytest.fixture
def world() -> World:
    w = World()
    w.add_asset("EURUSD")
    return w


async def until(condition: object, timeout_s: float = 2.0) -> None:
    async with asyncio.timeout(timeout_s):
        while not condition():  # type: ignore[operator]  # noqa: ASYNC110
            await asyncio.sleep(0.002)


# ---- connecting ------------------------------------------------------------------------------


async def test_a_failed_connect_raises_and_leaves_the_adapter_disconnected(world: World) -> None:
    world.connect_failures.append(QuotexConnectionError("bad password"))
    adapter, _, _, tasks = build(world)
    with pytest.raises(QuotexConnectionError, match="bad password"):
        await adapter.connect()
    assert adapter.state is ConnectionState.DISCONNECTED
    assert world.clients_closed == world.clients_made == 1  # the half-open client was closed
    await tasks.shutdown()


async def test_unexpected_library_errors_are_wrapped(world: World) -> None:
    world.connect_failures.append(OSError("getaddrinfo failed"))
    adapter, _, _, tasks = build(world)
    with pytest.raises(QuotexConnectionError, match="getaddrinfo failed"):
        await adapter.connect()
    await tasks.shutdown()


async def test_connect_gives_up_when_the_library_hangs(world: World) -> None:
    world.connect_hangs = True
    adapter, _, _, tasks = build(world, connect_timeout_s=0.05)
    with pytest.raises(QuotexConnectionError, match="TimeoutError"):
        await adapter.connect()
    assert world.clients_closed == 1
    await tasks.shutdown()


async def test_retry_forever_backs_off_exponentially_until_it_works(world: World) -> None:
    world.connect_failures.extend(QuotexConnectionError("down") for _ in range(4))
    adapter, _, sleeps, tasks = build(world)
    await adapter.connect(retry_forever=True)
    assert adapter.state is ConnectionState.CONNECTED
    assert sleeps.delays == [1, 2, 4, 8]
    await adapter.disconnect()
    await tasks.shutdown()


async def test_disconnect_stops_a_connect_that_retries_forever(world: World) -> None:
    world.connect_failures.extend(QuotexConnectionError("down") for _ in range(1000))
    adapter, _, _, tasks = build(world)
    attempt = asyncio.create_task(adapter.connect(retry_forever=True))
    await until(lambda: world.clients_made >= 3)
    await adapter.disconnect()
    with pytest.raises(QuotexConnectionError):
        await asyncio.wait_for(attempt, 2)
    assert adapter.state is ConnectionState.DISCONNECTED
    await tasks.shutdown()


async def test_connecting_twice_does_nothing_the_second_time(world: World) -> None:
    adapter, _, _, tasks = build(world)
    await adapter.connect()
    await adapter.connect()
    assert world.clients_made == 1
    await adapter.disconnect()
    await tasks.shutdown()


async def test_cancelling_connect_closes_the_client(world: World) -> None:
    world.connect_hangs = True
    adapter, _, _, tasks = build(world, connect_timeout_s=60)
    attempt = asyncio.create_task(adapter.connect())
    await until(lambda: world.clients_made == 1)
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt
    assert world.clients_closed == 1
    await tasks.shutdown()


# ---- reconnecting ----------------------------------------------------------------------------


async def test_a_lost_connection_is_re_established_with_backoff(world: World) -> None:
    adapter, bus, sleeps, tasks = build(world)
    events = bus.subscribe(ConnectionChanged)
    await adapter.connect()
    await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert world.prepared == [("EURUSD", 60)]

    world.connected = False  # the websocket dropped
    world.connect_failures.extend(QuotexConnectionError("still down") for _ in range(2))
    await until(lambda: adapter.state is ConnectionState.CONNECTED and world.clients_made == 4)

    assert sleeps.delays == [1, 2]
    assert world.clients_closed >= 3  # old client + two failed attempts were cleaned up
    states = []
    while (event := events.get_nowait()) is not None:
        assert isinstance(event, ConnectionChanged)
        states.append(event.detail)
    assert states == ["connecting", "connected", "connection lost", "connected"]

    # The new connection starts with no price subscriptions, so the next order makes them again.
    await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert world.prepared == [("EURUSD", 60), ("EURUSD", 60)]
    await adapter.disconnect()
    await tasks.shutdown()


async def test_orders_are_refused_while_reconnecting(world: World) -> None:
    from app.quotex.errors import NotConnectedError

    adapter, _, _, tasks = build(world)
    await adapter.connect()
    world.connect_failures.extend(QuotexConnectionError("down") for _ in range(10_000))
    world.connected = False  # the websocket drops and every reconnect attempt fails
    await until(lambda: adapter.state is ConnectionState.RECONNECTING)
    with pytest.raises(NotConnectedError, match="reconnecting"):
        await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert len(world.sent) == 0
    await adapter.disconnect()
    await tasks.shutdown()


async def test_the_account_choice_survives_a_reconnect(world: World) -> None:
    adapter, _, _, tasks = build(world, allow_real=True)
    await adapter.connect()
    await adapter.set_account_type(AccountType.REAL)
    assert world.account_changes == [False]
    world.connected = False
    await until(lambda: world.clients_made == 2 and adapter.state is ConnectionState.CONNECTED)
    assert world.demo is False  # reconnected on the real account, not silently back on demo
    await adapter.disconnect()
    await tasks.shutdown()


# ---- safety and ordering ---------------------------------------------------------------------


async def test_orders_are_sent_one_at_a_time(world: World) -> None:
    """pyquotex has one shared 'order confirmed' slot: two orders in flight could swap answers."""
    world.buy_delay_s = 0.01
    adapter, _, _, tasks = build(world)
    await adapter.connect()
    acks = await asyncio.gather(
        *(adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00")) for _ in range(6))
    )
    assert world.max_in_flight == 1
    assert len({a.order_id for a in acks}) == 6
    await adapter.disconnect()
    await tasks.shutdown()


async def test_a_failed_order_does_not_block_the_next_one(world: World) -> None:
    world.order_failures.append(OrderRejectedError("nope"))
    adapter, _, _, tasks = build(world)
    await adapter.connect()
    with pytest.raises(OrderRejectedError):
        await adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    ack = await asyncio.wait_for(adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00")), 1)
    assert ack.order_id
    await adapter.disconnect()
    await tasks.shutdown()


async def test_switching_account_tells_the_connection(world: World) -> None:
    adapter, _, _, tasks = build(world, allow_real=True)
    await adapter.connect()
    await adapter.set_account_type(AccountType.REAL)
    await adapter.set_account_type(AccountType.REAL)  # no second request
    await adapter.set_account_type(AccountType.DEMO)
    assert world.account_changes == [False, True]
    balance = adapter.balance()
    assert balance is not None and balance.balance == D("10000.50")
    await adapter.disconnect()
    await tasks.shutdown()


async def test_bad_payout_data_stops_the_payout_read_loudly(world: World) -> None:
    world.rows.append(make_row("BROKEN", payout_1m=8500))  # looks like a layout change
    adapter, _, _, tasks = build(world)
    await adapter.connect()
    with pytest.raises(PayoutSanityError, match="outside 0-100"):
        adapter.payout("BROKEN", 1)
    assert adapter.payout("EURUSD", 1) == 85  # other assets are unaffected
    await adapter.disconnect()
    await tasks.shutdown()


# ---- balance events --------------------------------------------------------------------------


async def test_balance_changes_are_published_once_each(world: World) -> None:
    adapter, bus, _, tasks = build(world)
    events = bus.subscribe(BalanceUpdated)
    await adapter.connect()
    await until(lambda: events.depth == 1)
    await asyncio.sleep(0.05)  # unchanged balance: nothing more is published
    assert events.depth == 1

    world.balance = {"demoBalance": 9999.0, "liveBalance": 0}
    await until(lambda: events.depth == 2)
    first, second = events.get_nowait(), events.get_nowait()
    assert isinstance(first, BalanceUpdated) and isinstance(second, BalanceUpdated)
    assert [first.snapshot.balance, second.snapshot.balance] == [D("10000.50"), D("9999.00")]
    assert first.snapshot.account_type is AccountType.DEMO
    await adapter.disconnect()
    await tasks.shutdown()


async def test_disconnect_leaves_no_background_task_behind(world: World) -> None:
    adapter, _, _, tasks = build(world)
    await adapter.connect()
    assert tasks.running == 1
    await adapter.disconnect()
    await asyncio.sleep(0)
    assert tasks.running == 0
    await tasks.shutdown()
