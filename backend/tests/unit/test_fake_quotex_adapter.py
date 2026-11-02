"""The fake's own scripting features (the shared behaviour is in tests/contract/)."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

import pytest

from app.core.clock import SystemClock
from app.domain.enums import Direction
from app.events.bus import EventBus
from app.events.types import BalanceUpdated
from app.quotex import FakeQuotexAdapter
from app.quotex.base import ConnectionState, TradeOutcome
from app.quotex.errors import NotConnectedError, OrderRejectedError, QuotexConnectionError

D = Decimal


def make(**kwargs: object) -> FakeQuotexAdapter:
    fake = FakeQuotexAdapter(clock=SystemClock(), **kwargs)  # type: ignore[arg-type]
    fake.add_asset("EURUSD", payout=80)
    return fake


async def test_default_result_is_a_win_at_the_asset_payout() -> None:
    fake = make()
    await fake.connect()
    ack = await fake.place_order("EURUSD", Direction.CALL, 60, D("10.00"))
    result = await fake.await_result(ack.order_id, 1)
    assert (result.outcome, result.profit) == (TradeOutcome.WON, D("8.00"))


async def test_outcomes_can_be_scripted_by_name() -> None:
    fake = make()
    await fake.connect()
    fake.script_results(TradeOutcome.LOST, TradeOutcome.DRAW, TradeOutcome.WON)
    results = []
    for _ in range(3):
        ack = await fake.place_order("EURUSD", Direction.CALL, 60, D("5.00"))
        results.append(await fake.await_result(ack.order_id, 1))
    assert [(r.outcome, r.profit) for r in results] == [
        (TradeOutcome.LOST, D("-5.00")),
        (TradeOutcome.DRAW, D("0.00")),
        (TradeOutcome.WON, D("4.00")),
    ]


async def test_balance_follows_the_stake_and_the_result() -> None:
    fake = make(balance=D("100.00"))
    await fake.connect()
    fake.script_results(TradeOutcome.WON, TradeOutcome.LOST, TradeOutcome.DRAW)
    expected = [D("108.00"), D("103.00"), D("103.00")]  # +8.00 win, -5.00 loss, draw refunds
    for stake, balance in zip(("10.00", "5.00", "5.00"), expected, strict=True):
        ack = await fake.place_order("EURUSD", Direction.CALL, 60, D(stake))
        await fake.await_result(ack.order_id, 1)
        snapshot = fake.balance()
        assert snapshot is not None and snapshot.balance == balance


async def test_balance_changes_are_published() -> None:
    bus = EventBus()
    updates = bus.subscribe(BalanceUpdated)
    fake = make(bus=bus, balance=D("100.00"))
    await fake.connect()
    await fake.place_order("EURUSD", Direction.CALL, 60, D("10.00"))
    balances = []
    while (event := updates.get_nowait()) is not None:
        assert isinstance(event, BalanceUpdated)
        balances.append(event.snapshot.balance)
    assert balances == [D("90.00"), D("108.00")]  # stake taken, then stake + winnings paid back


async def test_a_held_order_stays_open_until_settled() -> None:
    fake = make(hold_results=True)
    await fake.connect()
    ack = await fake.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    waiting = asyncio.create_task(fake.await_result(ack.order_id, 5))
    await asyncio.sleep(0.02)
    assert not waiting.done()
    fake.settle(ack.order_id)
    assert (await asyncio.wait_for(waiting, 1)).outcome is TradeOutcome.WON


async def test_a_result_delay_is_honoured() -> None:
    fake = make(result_delay_s=0.05)
    await fake.connect()
    ack = await fake.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    started = time.perf_counter()
    await fake.await_result(ack.order_id, 1)
    assert time.perf_counter() - started >= 0.03


async def test_an_ack_delay_is_honoured() -> None:
    fake = make(ack_delay_s=0.05)
    await fake.connect()
    ack = await fake.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert (ack.t_order_acked_ns - ack.t_order_sent_ns) >= 40_000_000


async def test_scripted_connect_failures() -> None:
    fake = make()
    fake.fail_next_connect()
    with pytest.raises(QuotexConnectionError, match="scripted"):
        await fake.connect()
    assert fake.state is ConnectionState.DISCONNECTED
    await fake.connect()
    assert fake.state is ConnectionState.CONNECTED
    assert fake.connect_attempts == 2


async def test_connection_loss_blocks_orders_until_restored() -> None:
    fake = make()
    await fake.connect()
    fake.simulate_connection_loss()
    assert fake.state is ConnectionState.RECONNECTING
    with pytest.raises(NotConnectedError):
        await fake.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    fake.simulate_connection_restored()
    await fake.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert len(fake.orders) == 1


async def test_orders_are_recorded_for_assertions() -> None:
    fake = make()
    await fake.connect()
    await fake.place_order("EURUSD", Direction.PUT, 300, D("2.50"))
    [order] = fake.orders
    assert (order.asset, order.direction, order.duration_s, order.amount) == (
        "EURUSD",
        Direction.PUT,
        300,
        D("2.50"),
    )


async def test_a_failed_order_is_not_recorded() -> None:
    fake = make()
    await fake.connect()
    fake.fail_next_order(OrderRejectedError("no"))
    with pytest.raises(OrderRejectedError):
        await fake.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert fake.orders == []


def test_payouts_outside_the_range_cannot_be_scripted() -> None:
    fake = make()
    with pytest.raises(ValueError, match="between 0 and 100"):
        fake.add_asset("BAD", payout=101)
