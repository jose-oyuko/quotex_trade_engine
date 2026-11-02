"""Contract tests: the behaviour every Quotex adapter must have.

The same tests run against `FakeQuotexAdapter` and against `PyQuotexAdapter` driven by a scripted
library seam (`ScriptedClient`). Whatever the fake does here, the real adapter must do too: the
fake is only a useful stand-in for the engine tests because of that. What neither can show is how
the real Quotex behaves; that is the live diagnostic's job.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import pytest

from app.core.clock import SystemClock
from app.core.tasks import TaskSupervisor
from app.domain.enums import AccountType, Direction
from app.events.bus import EventBus
from app.events.types import ConnectionChanged
from app.quotex import FakeQuotexAdapter, PyQuotexAdapter
from app.quotex.base import ConnectionState, QuotexAdapter, TradeOutcome
from app.quotex.errors import (
    AccountMismatchError,
    AssetClosedError,
    InvalidOrderError,
    NotConnectedError,
    OrderAckTimeoutError,
    OrderRejectedError,
    RealAccountNotAllowedError,
    ResultTimeoutError,
)
from tests.quotex_support import ScriptedClient, World

D = Decimal


class Harness(Protocol):
    adapter: QuotexAdapter
    bus: EventBus

    def add_asset(self, asset: str, *, payout: int = 85, is_open: bool = True) -> None: ...
    def set_open(self, asset: str, is_open: bool) -> None: ...
    def script_profits(self, *profits: Decimal) -> None: ...
    def fail_next_order(self, error: Exception) -> None: ...
    def hold_results(self) -> None: ...
    def wrong_account(self) -> None: ...
    def sent_orders(self) -> int: ...
    def prepare_calls(self) -> int: ...
    def balance_is(self, amount: Decimal) -> None: ...
    def make_adapter(self, *, account_type: AccountType, allow_real: bool) -> QuotexAdapter: ...
    async def close(self) -> None: ...


@dataclass
class FakeHarness:
    adapter: FakeQuotexAdapter
    bus: EventBus

    def add_asset(self, asset: str, *, payout: int = 85, is_open: bool = True) -> None:
        self.adapter.add_asset(asset, payout=payout, is_open=is_open)

    def set_open(self, asset: str, is_open: bool) -> None:
        self.adapter.set_open(asset, is_open)

    def script_profits(self, *profits: Decimal) -> None:
        self.adapter.script_results(*profits)

    def fail_next_order(self, error: Exception) -> None:
        self.adapter.fail_next_order(error)  # type: ignore[arg-type]

    def hold_results(self) -> None:
        self.adapter.hold_results = True

    def wrong_account(self) -> None:
        self.adapter.simulate_wrong_account()

    def sent_orders(self) -> int:
        return len(self.adapter.orders)

    def prepare_calls(self) -> int:
        return len(self.adapter.prepare_calls)

    def balance_is(self, amount: Decimal) -> None:
        self.adapter._balance = amount

    def make_adapter(self, *, account_type: AccountType, allow_real: bool) -> QuotexAdapter:
        return FakeQuotexAdapter(
            clock=SystemClock(), account_type=account_type, allow_real=allow_real
        )

    async def close(self) -> None:
        await self.adapter.disconnect()


@dataclass
class RealHarness:
    adapter: PyQuotexAdapter
    bus: EventBus
    world: World
    tasks: TaskSupervisor

    def add_asset(self, asset: str, *, payout: int = 85, is_open: bool = True) -> None:
        self.world.add_asset(asset, payout_1m=payout, payout_5m=payout, is_open=is_open)

    def set_open(self, asset: str, is_open: bool) -> None:
        self.world.set_open(asset, is_open)

    def script_profits(self, *profits: Decimal) -> None:
        self.world.results.extend(profits)

    def fail_next_order(self, error: Exception) -> None:
        self.world.order_failures.append(error)  # type: ignore[arg-type]

    def hold_results(self) -> None:
        self.world.hold_results = True

    def wrong_account(self) -> None:
        self.world.demo = not self.world.demo

    def sent_orders(self) -> int:
        return len(self.world.sent)

    def prepare_calls(self) -> int:
        return len(self.world.prepared)

    def balance_is(self, amount: Decimal) -> None:
        self.world.balance = {"demoBalance": float(amount), "liveBalance": 0}

    def make_adapter(self, *, account_type: AccountType, allow_real: bool) -> QuotexAdapter:
        return PyQuotexAdapter(
            lambda: ScriptedClient(self.world),
            tasks=self.tasks,
            clock=SystemClock(),
            account_type=account_type,
            allow_real=allow_real,
        )

    async def close(self) -> None:
        await self.adapter.disconnect()
        await self.tasks.shutdown()


@pytest.fixture(params=["fake", "real"])
async def harness(request: pytest.FixtureRequest) -> AsyncIterator[Harness]:
    bus = EventBus()
    h: Harness
    if request.param == "fake":
        h = FakeHarness(FakeQuotexAdapter(clock=SystemClock(), bus=bus), bus)
    else:
        world, tasks = World(), TaskSupervisor()
        adapter = PyQuotexAdapter(
            lambda: ScriptedClient(world),
            tasks=tasks,
            clock=SystemClock(),
            bus=bus,
            monitor_interval_s=0.01,
        )
        h = RealHarness(adapter, bus, world, tasks)
    h.add_asset("EURUSD", payout=85)
    h.add_asset("GBPUSD_otc", payout=90)
    h.add_asset("AUDUSD", payout=70, is_open=False)
    yield h
    await h.close()


@pytest.fixture
async def connected(harness: Harness) -> Harness:
    await harness.adapter.connect()
    return harness


# ---- connection ------------------------------------------------------------------------------


async def test_starts_disconnected_on_the_demo_account(harness: Harness) -> None:
    assert harness.adapter.state is ConnectionState.DISCONNECTED
    assert harness.adapter.account_type is AccountType.DEMO
    assert harness.adapter.balance() is None


async def test_connect_and_disconnect(harness: Harness) -> None:
    await harness.adapter.connect()
    assert harness.adapter.state is ConnectionState.CONNECTED
    await harness.adapter.disconnect()
    assert harness.adapter.state is ConnectionState.DISCONNECTED


async def test_connection_changes_are_published_as_events(harness: Harness) -> None:
    subscription = harness.bus.subscribe(ConnectionChanged)
    await harness.adapter.connect()
    await harness.adapter.disconnect()
    seen = []
    while (event := subscription.get_nowait()) is not None:
        assert isinstance(event, ConnectionChanged)
        seen.append((event.component, event.connected))
    assert seen[-2:] == [("quotex", True), ("quotex", False)]


async def test_real_account_needs_explicit_permission(harness: Harness) -> None:
    with pytest.raises(RealAccountNotAllowedError):
        harness.make_adapter(account_type=AccountType.REAL, allow_real=False)
    await harness.adapter.connect()
    with pytest.raises(RealAccountNotAllowedError):
        await harness.adapter.set_account_type(AccountType.REAL)
    assert harness.adapter.account_type is AccountType.DEMO


async def test_real_account_can_be_chosen_when_allowed(harness: Harness) -> None:
    adapter = harness.make_adapter(account_type=AccountType.DEMO, allow_real=True)
    await adapter.set_account_type(AccountType.REAL)
    assert adapter.account_type is AccountType.REAL


# ---- reads from memory -----------------------------------------------------------------------


async def test_balance_is_a_two_decimal_snapshot_of_the_active_account(connected: Harness) -> None:
    connected.balance_is(D("10000.50"))
    snapshot = connected.adapter.balance()
    assert snapshot is not None
    assert snapshot.account_type is AccountType.DEMO
    assert snapshot.balance == D("10000.50")
    assert (await connected.adapter.refresh_balance()).balance == D("10000.50")


async def test_payout_is_a_percentage_between_0_and_100(connected: Harness) -> None:
    payout = connected.adapter.payout("EURUSD", 1)
    assert payout == 85
    assert connected.adapter.payout("GBPUSD_otc", 5) == 90
    assert connected.adapter.payout("NOPE", 1) is None


async def test_is_open_distinguishes_open_closed_and_unknown(connected: Harness) -> None:
    assert connected.adapter.is_open("EURUSD") is True
    assert connected.adapter.is_open("AUDUSD") is False
    assert connected.adapter.is_open("NOPE") is False
    connected.set_open("EURUSD", False)
    assert connected.adapter.is_open("EURUSD") is False


# ---- orders ----------------------------------------------------------------------------------


async def test_order_is_acked_and_can_win(connected: Harness) -> None:
    connected.script_profits(D("0.85"))
    ack = await connected.adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert ack.order_id
    assert ack.t_order_acked_ns >= ack.t_order_sent_ns > 0
    result = await connected.adapter.await_result(ack.order_id, 1)
    assert result.order_id == ack.order_id
    assert result.outcome is TradeOutcome.WON
    assert result.profit == D("0.85")


async def test_a_losing_order_has_a_negative_profit(connected: Harness) -> None:
    connected.script_profits(D("-2.50"))
    ack = await connected.adapter.place_order("EURUSD", Direction.PUT, 60, D("2.50"))
    result = await connected.adapter.await_result(ack.order_id, 1)
    assert result.outcome is TradeOutcome.LOST
    assert result.profit == D("-2.50")


async def test_results_follow_the_script_in_placement_order(connected: Harness) -> None:
    connected.script_profits(D("-1.00"), D("-2.00"), D("2.50"))
    acks = [
        await connected.adapter.place_order("EURUSD", Direction.CALL, 60, D(stake))
        for stake in ("1.00", "2.00", "3.00")
    ]
    profits = [(await connected.adapter.await_result(a.order_id, 1)).profit for a in acks]
    assert profits == [D("-1.00"), D("-2.00"), D("2.50")]


async def test_concurrent_orders_all_get_their_own_id(connected: Harness) -> None:
    acks = await asyncio.gather(
        *(connected.adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00")) for _ in range(5))
    )
    assert len({a.order_id for a in acks}) == 5
    assert connected.sent_orders() == 5


async def test_the_price_subscription_is_made_once_per_asset(connected: Harness) -> None:
    for _ in range(3):
        await connected.adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    await connected.adapter.place_order("GBPUSD_otc", Direction.CALL, 60, D("1.00"))
    assert connected.prepare_calls() == 2
    await connected.adapter.prepare_asset("EURUSD", 60)  # explicit prepare is idempotent too
    assert connected.prepare_calls() == 2


@pytest.mark.parametrize("asset", ["AUDUSD", "NOPE"])
async def test_closed_or_unknown_assets_are_refused_before_anything_is_sent(
    connected: Harness, asset: str
) -> None:
    with pytest.raises(AssetClosedError):
        await connected.adapter.place_order(asset, Direction.CALL, 60, D("1.00"))
    assert connected.sent_orders() == 0


@pytest.mark.parametrize(
    ("duration_s", "amount"),
    [
        (60, D("0")),
        (60, D("-1.00")),
        (60, D("1.005")),
        (0, D("1.00")),
        (-60, D("1.00")),
        (60, D("NaN")),
    ],
)
async def test_invalid_orders_are_refused_before_anything_is_sent(
    connected: Harness, duration_s: int, amount: Decimal
) -> None:
    with pytest.raises(InvalidOrderError):
        await connected.adapter.place_order("EURUSD", Direction.CALL, duration_s, amount)
    assert connected.sent_orders() == 0


async def test_a_float_amount_is_refused(connected: Harness) -> None:
    with pytest.raises(InvalidOrderError):
        await connected.adapter.place_order("EURUSD", Direction.CALL, 60, 1.5)  # type: ignore[arg-type]
    assert connected.sent_orders() == 0


async def test_orders_need_a_connection(harness: Harness) -> None:
    with pytest.raises(NotConnectedError):
        await harness.adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    with pytest.raises(NotConnectedError):
        await harness.adapter.await_result("x", 1)


async def test_a_rejected_order_is_reported_as_not_placed(connected: Harness) -> None:
    connected.fail_next_order(OrderRejectedError("insufficient balance"))
    with pytest.raises(OrderRejectedError, match="insufficient"):
        await connected.adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert connected.sent_orders() == 0
    # ... and the adapter is still usable afterwards.
    await connected.adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert connected.sent_orders() == 1


async def test_a_missing_confirmation_is_reported_as_possibly_placed(connected: Harness) -> None:
    connected.fail_next_order(OrderAckTimeoutError("no confirmation"))
    with pytest.raises(OrderAckTimeoutError) as caught:
        await connected.adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert caught.value.may_have_been_placed is True


async def test_an_order_on_the_wrong_account_is_never_sent(connected: Harness) -> None:
    connected.wrong_account()
    with pytest.raises(AccountMismatchError):
        await connected.adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert connected.sent_orders() == 0


async def test_waiting_for_a_result_times_out_without_pretending_a_loss(
    connected: Harness,
) -> None:
    connected.hold_results()
    ack = await connected.adapter.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    with pytest.raises(ResultTimeoutError):
        await connected.adapter.await_result(ack.order_id, 0.05)
