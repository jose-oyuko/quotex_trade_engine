"""The real `DerivAdapter` over a real WebSocket, against the local fake Deriv (tests/deriv_server).

The same behaviours as the Quotex contract (tests/contract), on Deriv's assets and rules, plus what
is Deriv's own: orders in flight at the same time, trade lengths per asset, the account checks.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest

from app.brokers.base import ConnectionState, TradeOutcome
from app.brokers.errors import (
    AccountMismatchError,
    AssetClosedError,
    BrokerConnectionError,
    DurationNotOfferedError,
    InvalidOrderError,
    LoginRejectedError,
    NotConnectedError,
    OrderAckTimeoutError,
    OrderRejectedError,
    RealAccountNotAllowedError,
    ResultTimeoutError,
)
from app.core.backoff import BackoffPolicy
from app.core.clock import SystemClock
from app.core.tasks import TaskSupervisor
from app.deriv import DerivAdapter
from app.domain.enums import AccountType, Direction
from app.events.bus import EventBus
from app.events.types import BalanceUpdated, ConnectionChanged
from tests.deriv_server import FakeDerivServer

D = Decimal


class Rig:
    def __init__(self, server: FakeDerivServer) -> None:
        self.server = server
        self.bus = EventBus()
        self.tasks = TaskSupervisor()
        self.delays: list[float] = []

    async def no_wait(self, seconds: float) -> None:
        self.delays.append(seconds)
        await asyncio.sleep(0)

    def adapter(self, **kwargs: object) -> DerivAdapter:
        options: dict[str, object] = {
            "tasks": self.tasks,
            "clock": SystemClock(),
            "bus": self.bus,
            "ack_timeout_s": 2.0,
            "connect_timeout_s": 5.0,
            "backoff": BackoffPolicy(base_s=1, cap_s=30, jitter=0.1),
            "sleep": self.no_wait,
            "rng": lambda: 0.5,
            "monitor_interval_s": 0.01,
            "preload_lengths": False,
            **kwargs,
        }
        return DerivAdapter(self.server.link, **options)  # type: ignore[arg-type]


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    server = FakeDerivServer()
    await server.start()
    rig = Rig(server)
    yield rig
    await rig.tasks.shutdown()
    await server.stop()


@pytest.fixture
async def deriv(rig: Rig) -> AsyncIterator[DerivAdapter]:
    adapter = rig.adapter()
    await adapter.connect()
    yield adapter
    await adapter.disconnect()


# ---- connection and account ------------------------------------------------------------------


async def test_connects_on_the_demo_account_and_reads_balance_and_assets(
    rig: Rig, deriv: DerivAdapter
) -> None:
    assert deriv.state is ConnectionState.CONNECTED
    assert deriv.account_type is AccountType.DEMO
    snapshot = deriv.balance()
    assert snapshot is not None and snapshot.balance == D("10000.00")
    assert deriv.currency == "USD"
    assert {a.asset for a in deriv.assets()} == {"EURUSD", "R_75", "AUDUSD"}
    assert deriv.is_open("EURUSD") and deriv.is_open("R_75")
    assert not deriv.is_open("AUDUSD")  # market closed
    assert not deriv.is_open("EURUSD_otc") and not deriv.is_open("NOPE")


async def test_connection_changes_are_published_as_deriv_events(rig: Rig) -> None:
    subscription = rig.bus.subscribe(ConnectionChanged)
    adapter = rig.adapter()
    await adapter.connect()
    await adapter.disconnect()
    seen = []
    while (event := subscription.get_nowait()) is not None:
        assert isinstance(event, ConnectionChanged)
        seen.append((event.component, event.connected))
    assert seen[-2:] == [("deriv", True), ("deriv", False)]


async def test_every_connection_uses_a_fresh_one_time_link(rig: Rig, deriv: DerivAdapter) -> None:
    await rig.server.drop_clients()
    for _ in range(200):
        if rig.server.connections == 2 and deriv.state is ConnectionState.CONNECTED:
            break
        await asyncio.sleep(0.01)
    assert rig.server.connections == 2
    assert len(set(rig.server.links_used)) == 2


async def test_a_demo_token_that_opens_a_real_account_is_refused(rig: Rig) -> None:
    rig.server.loginids[AccountType.DEMO] = "CR999"
    adapter = rig.adapter()
    with pytest.raises(LoginRejectedError, match="CR999"):
        await adapter.connect(retry_forever=True)  # a refused login is never retried
    assert adapter.state is ConnectionState.DISCONNECTED


async def test_a_new_style_demo_account_number_is_accepted(rig: Rig) -> None:
    rig.server.loginids[AccountType.DEMO] = "DOT90004580"
    adapter = rig.adapter()
    await adapter.connect()  # a new-style demo number is accepted on the demo slot
    try:
        assert adapter.state is ConnectionState.CONNECTED
    finally:
        await adapter.disconnect()


async def test_an_unknown_account_number_relies_on_the_list_and_the_link(rig: Rig) -> None:
    rig.server.loginids[AccountType.DEMO] = "XYZ123"
    adapter = rig.adapter()
    await adapter.connect()
    try:
        assert adapter.state is ConnectionState.CONNECTED
    finally:
        await adapter.disconnect()


async def test_real_needs_permission_and_a_real_token(rig: Rig) -> None:
    with pytest.raises(RealAccountNotAllowedError):
        rig.adapter(account_type=AccountType.REAL)
    adapter = rig.adapter()
    await adapter.connect()
    try:
        with pytest.raises(RealAccountNotAllowedError, match="not enabled"):
            await adapter.set_account_type(AccountType.REAL)
        adapter.set_real_allowed(True)
        with pytest.raises(RealAccountNotAllowedError, match="no Deriv token"):
            await adapter.set_account_type(AccountType.REAL)
        assert adapter.account_type is AccountType.DEMO
    finally:
        await adapter.disconnect()


async def test_switching_to_real_opens_the_real_account(rig: Rig) -> None:
    adapter = rig.adapter(allow_real=True, real_available=True)
    await adapter.connect()
    try:
        await adapter.set_account_type(AccountType.REAL)
        assert adapter.account_type is AccountType.REAL
        assert adapter.state is ConnectionState.CONNECTED
        snapshot = adapter.balance()
        assert snapshot is not None and snapshot.balance == D("50.00")
        assert rig.server.links_used[-1].startswith("/ws/real")
    finally:
        await adapter.disconnect()


async def test_reconnects_with_backoff_after_a_drop(rig: Rig, deriv: DerivAdapter) -> None:
    await rig.server.stop()  # nothing to reconnect to for a while
    await rig.server.drop_clients()
    for _ in range(300):
        if len(rig.delays) >= 2:
            break
        await asyncio.sleep(0.01)
    assert rig.delays[:2] == [1.0, 2.0]
    assert deriv.state is ConnectionState.RECONNECTING
    with pytest.raises(NotConnectedError):
        await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))


# ---- payouts and trade lengths ---------------------------------------------------------------


async def test_the_payout_is_read_from_a_price_quote_once_prepared(deriv: DerivAdapter) -> None:
    assert deriv.payout("R_75", 1) is None  # not asked yet: never guessed
    await deriv.prepare_asset("R_75", 60)
    await deriv.prepare_asset("R_75", 300)
    await deriv.prepare_asset("EURUSD", 900)
    assert deriv.payout("R_75", 1) == 95
    assert deriv.payout("R_75", 5) == 95
    assert deriv.payout("EURUSD", 15) == 80


async def test_a_trade_length_the_asset_does_not_offer_is_refused_before_sending(
    rig: Rig, deriv: DerivAdapter
) -> None:
    with pytest.raises(DurationNotOfferedError, match="15 min to 365 days"):
        await deriv.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    assert rig.server.sent("buy") == []
    assert await deriv.trade_lengths("R_75") is not None


async def test_the_lengths_ignore_tick_trades_and_higher_lower(deriv: DerivAdapter) -> None:
    lengths = await deriv.trade_lengths("EURUSD")
    assert lengths is not None and [(r.min_s, r.max_s) for r in lengths] == [(900, 365 * 86400)]
    lengths = await deriv.trade_lengths("R_75")
    assert lengths is not None and [(r.min_s, r.max_s) for r in lengths] == [(15, 86400)]


async def test_lengths_deriv_writes_in_a_form_we_cannot_read_leave_the_decision_to_deriv(
    rig: Rig, deriv: DerivAdapter
) -> None:
    rig.server.offers["R_75"] = [
        {
            "barriers": 1,
            "contract_category": "callput",
            "contract_type": "CALL",
            "expiry_type": "intraday",
            "min_contract_duration": "5",
            "max_contract_duration": "10",
        }
    ]
    assert await deriv.trade_lengths("R_75") is None
    ack = await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))
    assert ack.order_id


async def test_no_price_quote_means_no_order(rig: Rig, deriv: DerivAdapter) -> None:
    rig.server.proposal_errors["R_75"] = {"code": "MarketIsClosed", "message": "Market closed."}
    with pytest.raises(OrderRejectedError, match="Market closed"):
        await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))
    assert rig.server.sent("buy") == []


# ---- orders ----------------------------------------------------------------------------------


async def test_a_synthetic_index_trade_at_one_minute_wins(rig: Rig, deriv: DerivAdapter) -> None:
    rig.server.profits.append(D("0.95"))
    ack = await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))
    assert ack.order_id.isdigit()
    assert ack.t_order_acked_ns >= ack.t_order_sent_ns > 0
    result = await deriv.await_result(ack.order_id, 2)
    assert (result.outcome, result.profit) == (TradeOutcome.WON, D("0.95"))
    buy = rig.server.sent("buy")[0]
    assert buy["buy"] == "1" and buy["price"] == 1.0
    assert buy["parameters"] == {
        "amount": 1.0,
        "basis": "stake",
        "contract_type": "CALL",
        "currency": "USD",
        "duration": 1,
        "duration_unit": "m",
        "underlying_symbol": "R_75",
    }


async def test_a_forex_trade_uses_deriv_s_symbol(rig: Rig, deriv: DerivAdapter) -> None:
    await deriv.place_order("EURUSD", Direction.PUT, 900, D("2.00"))
    parameters = rig.server.sent("buy")[0]["parameters"]
    assert parameters["underlying_symbol"] == "frxEURUSD"
    assert (parameters["contract_type"], parameters["duration"]) == ("PUT", 15)


async def test_a_loss_and_an_equal_exit_are_negative_and_lost(
    rig: Rig, deriv: DerivAdapter
) -> None:
    rig.server.profits.extend([D("-2.50"), D("-1.00")])
    first = await deriv.place_order("R_75", Direction.PUT, 60, D("2.50"))
    second = await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))
    assert (await deriv.await_result(first.order_id, 2)).profit == D("-2.50")
    result = await deriv.await_result(second.order_id, 2)
    assert (result.outcome, result.profit) == (TradeOutcome.LOST, D("-1.00"))


async def test_two_orders_in_flight_answered_in_reverse_get_their_own_confirmation(
    rig: Rig, deriv: DerivAdapter
) -> None:
    """Decision D-77: no lock. Both legs of a pair go out together; Deriv's replies can come back
    in any order and each order still gets its own contract."""
    await deriv.prepare_asset("R_75", 60)
    rig.server.reverse_orders = 2
    call, put = await asyncio.gather(
        deriv.place_order("R_75", Direction.CALL, 60, D("1.00")),
        deriv.place_order("R_75", Direction.PUT, 60, D("2.00")),
    )
    assert call.order_id != put.order_id
    assert rig.server.contracts[int(call.order_id)].contract_type == "CALL"
    assert rig.server.contracts[int(put.order_id)].contract_type == "PUT"
    assert rig.server.contracts[int(put.order_id)].stake == D("2.00")


async def test_many_concurrent_orders_all_get_their_own_id(rig: Rig, deriv: DerivAdapter) -> None:
    acks = await asyncio.gather(
        *(deriv.place_order("R_75", Direction.CALL, 60, D("1.00")) for _ in range(5))
    )
    assert len({a.order_id for a in acks}) == 5
    assert len(rig.server.sent("buy")) == 5


async def test_the_price_quote_is_made_once_per_asset_and_length(
    rig: Rig, deriv: DerivAdapter
) -> None:
    for _ in range(3):
        await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))
    await deriv.place_order("R_75", Direction.CALL, 300, D("1.00"))
    assert len(rig.server.sent("proposal")) == 2
    assert len(rig.server.sent("contracts_for")) == 1


@pytest.mark.parametrize("asset", ["AUDUSD", "NOPE", "EURUSD_otc"])
async def test_closed_unknown_or_otc_assets_are_refused_before_sending(
    rig: Rig, deriv: DerivAdapter, asset: str
) -> None:
    with pytest.raises(AssetClosedError):
        await deriv.place_order(asset, Direction.CALL, 900, D("1.00"))
    assert rig.server.sent("buy") == []


@pytest.mark.parametrize(
    ("duration_s", "amount"), [(60, D("0")), (60, D("1.005")), (0, D("1.00")), (60, D("NaN"))]
)
async def test_invalid_orders_are_refused_before_sending(
    rig: Rig, deriv: DerivAdapter, duration_s: int, amount: Decimal
) -> None:
    with pytest.raises(InvalidOrderError):
        await deriv.place_order("R_75", Direction.CALL, duration_s, amount)
    assert rig.server.sent("buy") == []


async def test_a_rejected_order_is_reported_as_not_placed(rig: Rig, deriv: DerivAdapter) -> None:
    rig.server.buy_errors.append({"code": "InsufficientBalance", "message": "Not enough money."})
    with pytest.raises(OrderRejectedError, match="Not enough money"):
        await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))
    assert rig.server.contracts == {}
    await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))  # still usable


async def test_no_confirmation_means_the_order_may_have_been_placed(
    rig: Rig,
) -> None:
    adapter = rig.adapter(ack_timeout_s=0.2)
    await adapter.connect()
    try:
        await adapter.prepare_asset("R_75", 60)
        rig.server.answer_orders = False
        with pytest.raises(OrderAckTimeoutError) as caught:
            await adapter.place_order("R_75", Direction.CALL, 60, D("1.00"))
        assert caught.value.may_have_been_placed is True
        assert len(rig.server.contracts) == 1  # it was, in fact, placed
    finally:
        await adapter.disconnect()


async def test_a_connection_lost_before_the_confirmation_may_have_placed_the_order(
    rig: Rig, deriv: DerivAdapter
) -> None:
    await deriv.prepare_asset("R_75", 60)
    rig.server.answer_orders = False
    order = asyncio.ensure_future(deriv.place_order("R_75", Direction.CALL, 60, D("1.00")))
    for _ in range(100):
        if rig.server.sent("buy"):
            break
        await asyncio.sleep(0.01)
    await rig.server.drop_clients()
    with pytest.raises(OrderAckTimeoutError):
        await order


async def test_an_order_on_the_wrong_account_is_never_sent(rig: Rig) -> None:
    adapter = rig.adapter(allow_real=True, real_available=True)
    await adapter.connect()
    try:
        adapter._connected_as = AccountType.REAL  # the socket is not on the account we believe
        with pytest.raises(AccountMismatchError):
            await adapter.place_order("R_75", Direction.CALL, 60, D("1.00"))
        assert rig.server.sent("buy") == []
    finally:
        await adapter.disconnect()


async def test_orders_and_results_need_a_connection(rig: Rig) -> None:
    adapter = rig.adapter()
    with pytest.raises(NotConnectedError):
        await adapter.place_order("R_75", Direction.CALL, 60, D("1.00"))
    with pytest.raises(NotConnectedError):
        await adapter.await_result("5001", 1)


# ---- results ---------------------------------------------------------------------------------


async def test_waiting_for_a_result_times_out_without_pretending_a_loss(
    rig: Rig, deriv: DerivAdapter
) -> None:
    rig.server.settle_after_s = None
    ack = await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))
    with pytest.raises(ResultTimeoutError):
        await deriv.await_result(ack.order_id, 0.1)


async def test_a_result_already_known_is_reported_at_once(rig: Rig, deriv: DerivAdapter) -> None:
    rig.server.settle_after_s = None
    ack = await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))
    await rig.server.settle(int(ack.order_id), D("-1.00"))
    result = await deriv.await_result(ack.order_id, 1)
    assert result.profit == D("-1.00")


async def test_results_are_matched_by_subscription_when_updates_carry_no_req_id(
    rig: Rig, deriv: DerivAdapter
) -> None:
    rig.server.stream_req_id = False
    rig.server.settle_after_s = None
    ack = await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))
    waiting = asyncio.ensure_future(deriv.await_result(ack.order_id, 2))
    await asyncio.sleep(0.05)
    await rig.server.settle(int(ack.order_id), D("0.95"))
    assert (await waiting).profit == D("0.95")


async def test_a_result_that_comes_during_a_reconnect_is_still_reported(
    rig: Rig, deriv: DerivAdapter
) -> None:
    rig.server.settle_after_s = None
    ack = await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))
    waiting = asyncio.ensure_future(deriv.await_result(ack.order_id, 5))
    await asyncio.sleep(0.05)
    await rig.server.drop_clients()
    await rig.server.settle(int(ack.order_id), D("0.95"))  # settles while we are away
    result = await waiting
    assert result.profit == D("0.95")


async def test_balance_changes_are_published(rig: Rig, deriv: DerivAdapter) -> None:
    subscription = rig.bus.subscribe(BalanceUpdated)
    rig.server.profits.append(D("0.95"))
    ack = await deriv.place_order("R_75", Direction.CALL, 60, D("1.00"))
    await deriv.await_result(ack.order_id, 2)
    for _ in range(100):
        snapshot = deriv.balance()
        if snapshot is not None and snapshot.balance == D("10000.95"):
            break
        await asyncio.sleep(0.01)
    seen = []
    while (event := subscription.get_nowait()) is not None:
        assert isinstance(event, BalanceUpdated)
        seen.append(event.snapshot.balance)
    assert seen == [D("9999.00"), D("10000.95")]


async def test_a_disconnect_stops_the_adapter_within_seconds(rig: Rig) -> None:
    adapter = rig.adapter()
    await adapter.connect()
    await rig.server.stop()
    await rig.server.drop_clients()
    async with asyncio.timeout(6):
        await adapter.disconnect()
    assert adapter.state is ConnectionState.DISCONNECTED


async def test_a_connect_that_cannot_reach_deriv_says_so(rig: Rig) -> None:
    async def nowhere(_: AccountType) -> str:
        return "ws://127.0.0.1:1/ws/demo?otp=x"

    adapter = DerivAdapter(
        nowhere, tasks=rig.tasks, clock=SystemClock(), connect_timeout_s=2.0, sleep=rig.no_wait
    )
    with pytest.raises(BrokerConnectionError):
        await adapter.connect()
    assert adapter.state is ConnectionState.DISCONNECTED


# ---- what is refused from memory, before a chain starts (Phase 20) ---------------------------


async def test_the_trade_lengths_of_every_open_asset_are_learned_in_the_background(
    rig: Rig,
) -> None:
    adapter = rig.adapter(preload_lengths=True, lengths_per_tick=1)
    await adapter.connect()
    try:
        assert adapter.order_refusal("EURUSD", 60) is None  # not known yet: Deriv would decide
        for _ in range(300):
            if adapter.order_refusal("EURUSD", 60) is not None:
                break
            await asyncio.sleep(0.01)
        assert adapter.order_refusal("EURUSD", 60) == (
            "Deriv does not offer 1 min Rise/Fall on EURUSD: it offers 15 min to 365 days"
        )
        assert adapter.order_refusal("EURUSD", 900) is None
        for _ in range(300):
            if "R_75" in {m["contracts_for"] for m in rig.server.sent("contracts_for")}:
                break
            await asyncio.sleep(0.01)
        assert adapter.order_refusal("R_75", 60) is None
        # each open asset is asked about once; a closed one is not asked about at all
        asked = [m["contracts_for"] for m in rig.server.sent("contracts_for")]
        assert sorted(asked) == ["R_75", "frxEURUSD"]
    finally:
        await adapter.disconnect()


async def test_assets_deriv_does_not_trade_are_refused_from_memory(deriv: DerivAdapter) -> None:
    assert deriv.order_refusal("EURUSD_otc", 900) == (
        "EURUSD_otc is an OTC pair: Deriv has no OTC pairs"
    )
    assert deriv.order_refusal("NOPE", 60) == "NOPE is not traded on Deriv"
    assert deriv.order_refusal("AUDUSD", 900) == "AUDUSD is closed on Deriv"
    assert deriv.order_refusal("R_75", 60) is None  # lengths not asked for (preloading is off)


# ---- the asset list for the dashboard (Phase 21) ----------------------------------------------


async def test_the_catalogue_lists_every_asset_with_the_lengths_learned_so_far(
    deriv: DerivAdapter,
) -> None:
    before = {a.asset: a for a in deriv.catalogue()}
    assert set(before) == {"EURUSD", "R_75", "AUDUSD"}
    assert before["EURUSD"].market == "forex" and before["EURUSD"].lengths is None
    assert before["AUDUSD"].is_open is False
    assert before["R_75"].name != "" and before["R_75"].market == "synthetic_index"

    await deriv.trade_lengths("EURUSD")
    after = {a.asset: a for a in deriv.catalogue()}
    assert after["EURUSD"].lengths == ((900, 365 * 86400),)
    assert after["R_75"].lengths is None  # not asked about yet
