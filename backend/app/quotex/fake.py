"""A deterministic, scriptable stand-in for Quotex. Used by every test and demo that must not touch
the real service (docs/CONVENTIONS.md, "Testing").

It follows the same rules as `PyQuotexAdapter` (same checks, same errors, same order of checks), so
engine tests that pass against it exercise the same paths as production. Its behaviour is defined
by the contract tests in tests/contract/, which both adapters must pass.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.core.clock import Clock
from app.domain.enums import AccountType, Direction
from app.domain.ids import new_id
from app.domain.records import BalanceSnapshotRecord
from app.events.bus import EventBus
from app.events.types import BalanceUpdated, ConnectionChanged
from app.quotex.base import (
    BalanceSnapshot,
    ConnectionState,
    OrderAck,
    TradeOutcome,
    TradeResult,
    classify_profit,
    validate_order,
)
from app.quotex.errors import (
    AccountMismatchError,
    AssetClosedError,
    NotConnectedError,
    QuotexConnectionError,
    QuotexError,
    RealAccountNotAllowedError,
    ResultTimeoutError,
)

CENT = Decimal("0.01")


@dataclass(slots=True)
class PlacedOrder:
    """What the fake recorded about an order, for assertions."""

    order_id: str
    asset: str
    direction: Direction
    duration_s: int
    amount: Decimal
    account_type: AccountType
    profit: Decimal
    outcome: TradeOutcome


@dataclass(slots=True)
class _Asset:
    payout_1m: int
    payout_5m: int
    open: bool


@dataclass(slots=True)
class _Pending:
    placed: PlacedOrder
    result: asyncio.Future[TradeResult] = field(default_factory=lambda: asyncio.Future())


class FakeQuotexAdapter:
    """Script it with `script_results`, `fail_next_order`, `set_open`, `simulate_connection_loss`...

    By default every result is a win at the asset's payout; orders settle immediately. Use
    `result_delay_s` for a delay, or `hold_results=True` and `settle(order_id)` to keep an order
    open for as long as a test needs.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        bus: EventBus | None = None,
        account_type: AccountType = AccountType.DEMO,
        allow_real: bool = False,
        balance: Decimal = Decimal("1000.00"),
        ack_delay_s: float = 0.0,
        result_delay_s: float = 0.0,
        hold_results: bool = False,
    ) -> None:
        if account_type is AccountType.REAL and not allow_real:
            raise RealAccountNotAllowedError("real trading is not enabled")
        self._clock = clock
        self._bus = bus
        self._account_type = account_type
        self._allow_real = allow_real
        self._balance = balance
        self.ack_delay_s = ack_delay_s
        self.result_delay_s = result_delay_s
        self.hold_results = hold_results

        self._state = ConnectionState.DISCONNECTED
        self._assets: dict[str, _Asset] = {}
        self._scripted: list[Decimal | TradeOutcome] = []
        self._order_failures: list[QuotexError] = []
        self._connect_failures: list[QuotexError] = []
        self._pending: dict[str, _Pending] = {}
        self._prepared: set[tuple[str, int]] = set()
        self._connection_is_demo = account_type is AccountType.DEMO
        self.orders: list[PlacedOrder] = []
        self.prepare_calls: list[tuple[str, int]] = []
        self.connect_attempts = 0

    # ---- scripting ---------------------------------------------------------------------------

    def add_asset(
        self, asset: str, *, payout: int = 85, payout_5m: int | None = None, is_open: bool = True
    ) -> None:
        for value in (payout, payout_5m if payout_5m is not None else payout):
            if not 0 <= value <= 100:
                raise ValueError("payout must be between 0 and 100")
        self._assets[asset] = _Asset(payout, payout if payout_5m is None else payout_5m, is_open)

    def set_open(self, asset: str, is_open: bool) -> None:
        self._assets[asset].open = is_open

    def script_results(self, *results: Decimal | TradeOutcome) -> None:
        """Queue the results of the next orders, in placement order. A `Decimal` is the exact
        profit; `TradeOutcome.WON/LOST/DRAW` use the asset payout / the full stake / zero."""
        self._scripted.extend(results)

    def fail_next_order(self, error: QuotexError) -> None:
        self._order_failures.append(error)

    def fail_next_connect(self, error: QuotexError | None = None) -> None:
        self._connect_failures.append(error or QuotexConnectionError("scripted connect failure"))

    def simulate_connection_loss(self) -> None:
        self._set_state(ConnectionState.RECONNECTING, "connection lost")
        self._prepared.clear()

    def simulate_connection_restored(self) -> None:
        self._set_state(ConnectionState.CONNECTED)

    def simulate_wrong_account(self) -> None:
        """Make the connection sit on the other account than the adapter believes."""
        self._connection_is_demo = not self._connection_is_demo

    def settle(self, order_id: str) -> None:
        """Release an order held by `hold_results=True`."""
        pending = self._pending[order_id]
        if not pending.result.done():
            self._deliver(pending)

    def settle_all(self) -> None:
        for order_id in list(self._pending):
            self.settle(order_id)

    # ---- QuotexAdapter -----------------------------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def account_type(self) -> AccountType:
        return self._account_type

    def _set_state(self, state: ConnectionState, detail: str | None = None) -> None:
        if state is self._state:
            return
        self._state = state
        if self._bus is not None:
            self._bus.publish(
                ConnectionChanged(
                    occurred_at=self._clock.now(),
                    component="quotex",
                    connected=state is ConnectionState.CONNECTED,
                    detail=detail or state.value,
                )
            )

    async def connect(self, *, retry_forever: bool = False) -> None:
        if self._state is ConnectionState.CONNECTED:
            return
        self._set_state(ConnectionState.CONNECTING)
        while True:
            self.connect_attempts += 1
            if self._connect_failures:
                error = self._connect_failures.pop(0)
                if retry_forever:
                    await asyncio.sleep(0)
                    continue
                self._set_state(ConnectionState.DISCONNECTED, str(error))
                raise error
            break
        self._connection_is_demo = self._account_type is AccountType.DEMO
        self._set_state(ConnectionState.CONNECTED)

    async def disconnect(self) -> None:
        self._set_state(ConnectionState.DISCONNECTED)

    def set_real_allowed(self, allowed: bool) -> None:
        self._allow_real = allowed

    async def set_account_type(self, account_type: AccountType) -> None:
        if account_type is AccountType.REAL and not self._allow_real:
            raise RealAccountNotAllowedError("real trading is not enabled")
        self._account_type = account_type
        self._connection_is_demo = account_type is AccountType.DEMO

    def balance(self) -> BalanceSnapshot | None:
        if self._state is not ConnectionState.CONNECTED:
            return None
        return BalanceSnapshot(self._account_type, self._balance, self._clock.now())

    async def refresh_balance(self) -> BalanceSnapshot:
        self._require_connected()
        snapshot = self.balance()
        if snapshot is None:
            raise NotConnectedError("no balance available")
        return snapshot

    def payout(self, asset: str, minutes: int) -> int | None:
        if self._state is not ConnectionState.CONNECTED or asset not in self._assets:
            return None
        known = self._assets[asset]
        return known.payout_1m if minutes < 5 else known.payout_5m

    def is_open(self, asset: str) -> bool:
        known = self._assets.get(asset)
        return self._state is ConnectionState.CONNECTED and known is not None and known.open

    async def prepare_asset(self, asset: str, duration_s: int) -> None:
        self._require_connected()
        if (asset, duration_s) not in self._prepared:
            self.prepare_calls.append((asset, duration_s))
            self._prepared.add((asset, duration_s))

    async def place_order(
        self, asset: str, direction: Direction, duration_s: int, amount: Decimal
    ) -> OrderAck:
        validate_order(direction, duration_s, amount)
        self._require_connected()
        if self._connection_is_demo != (self._account_type is AccountType.DEMO):
            raise AccountMismatchError("connection is on the other account; order not sent")
        if not self.is_open(asset):
            raise AssetClosedError(f"{asset} is unknown or closed; order not sent")
        await self.prepare_asset(asset, duration_s)

        t_sent = self._clock.monotonic_ns()
        if self.ack_delay_s:
            await asyncio.sleep(self.ack_delay_s)
        if self._order_failures:
            raise self._order_failures.pop(0)
        t_acked = self._clock.monotonic_ns()

        outcome, profit = self._next_result(asset, duration_s, amount)
        placed = PlacedOrder(
            order_id=str(new_id()),
            asset=asset,
            direction=direction,
            duration_s=duration_s,
            amount=amount,
            account_type=self._account_type,
            profit=profit,
            outcome=outcome,
        )
        self.orders.append(placed)
        self._set_balance(self._balance - amount)  # Quotex takes the stake when the order opens
        pending = _Pending(placed)
        self._pending[placed.order_id] = pending
        if not self.hold_results:
            if self.result_delay_s:
                asyncio.get_running_loop().call_later(self.result_delay_s, self._deliver, pending)
            else:
                self._deliver(pending)
        return OrderAck(placed.order_id, t_sent, t_acked)

    async def await_result(self, order_id: str, timeout_s: float) -> TradeResult:
        self._require_connected()
        pending = self._pending.get(order_id)
        if pending is None:
            raise ResultTimeoutError(f"unknown order {order_id}")
        try:
            async with asyncio.timeout(timeout_s):
                return await asyncio.shield(pending.result)
        except TimeoutError as exc:
            raise ResultTimeoutError(
                f"order {order_id} did not settle within {timeout_s:g}s"
            ) from exc

    # ---- internals ---------------------------------------------------------------------------

    def _require_connected(self) -> None:
        if self._state is not ConnectionState.CONNECTED:
            raise NotConnectedError(f"not connected to Quotex (state: {self._state.value})")

    def _next_result(
        self, asset: str, duration_s: int, amount: Decimal
    ) -> tuple[TradeOutcome, Decimal]:
        scripted = self._scripted.pop(0) if self._scripted else TradeOutcome.WON
        if isinstance(scripted, Decimal):
            return classify_profit(scripted), scripted
        if scripted is TradeOutcome.WON:
            payout = self.payout(asset, duration_s // 60) or 0
            return scripted, (amount * payout / 100).quantize(CENT, rounding=ROUND_HALF_UP)
        if scripted is TradeOutcome.LOST:
            return scripted, -amount
        return scripted, Decimal("0.00")

    def _deliver(self, pending: _Pending) -> None:
        placed = pending.placed
        if pending.result.done():
            return
        # Quotex pays the stake back with the winnings; a draw returns the stake only.
        if placed.outcome is TradeOutcome.WON:
            self._set_balance(self._balance + placed.amount + placed.profit)
        elif placed.outcome is TradeOutcome.DRAW:
            self._set_balance(self._balance + placed.amount)
        pending.result.set_result(TradeResult(placed.order_id, placed.outcome, placed.profit))

    def _set_balance(self, balance: Decimal) -> None:
        if balance == self._balance:
            return
        self._balance = balance
        if self._bus is not None:
            now = self._clock.now()
            self._bus.publish(
                BalanceUpdated(
                    occurred_at=now,
                    snapshot=BalanceSnapshotRecord(
                        id=new_id(),
                        taken_at=now,
                        account_type=self._account_type,
                        balance=balance,
                    ),
                )
            )
