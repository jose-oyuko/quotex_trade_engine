"""Test doubles for the Quotex adapters.

`World` is a pretend Quotex: its instruments, balance and order log. `ScriptedClient` is the
`QuotexClient` the real adapter talks to, backed by a `World`; a new client per (re)connect shares
the same world, like a real reconnect reaches the same Quotex.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import count
from typing import Any

from app.domain.enums import Direction
from app.quotex.errors import QuotexConnectionError, QuotexError, ResultTimeoutError

ROW_LENGTH = 25  # more than the 19 columns the library layout needs


def make_row(
    symbol: str, *, is_open: bool = True, payout_1m: Any = 85, payout_5m: Any = 80
) -> list[Any]:
    """An instrument row with the fields at the positions pyquotex 1.1.0 reads them from."""
    row: list[Any] = [None] * ROW_LENGTH
    row[0] = 1
    row[1] = symbol
    row[2] = symbol.replace("_otc", " (OTC)")
    row[5] = payout_1m
    row[14] = is_open
    row[18] = payout_1m
    row[-10] = 90
    row[-9] = payout_1m
    row[-8] = payout_5m
    return row


@dataclass
class SentOrder:
    order_id: str
    asset: str
    direction: Direction
    duration_s: int
    amount: Decimal
    profit: Decimal


@dataclass
class World:
    rows: list[list[Any]] = field(default_factory=list)
    balance: dict[str, Any] | None = field(
        default_factory=lambda: {"demoBalance": 10000.5, "liveBalance": 25.0}
    )
    connected: bool = False
    demo: bool = True
    results: list[Decimal] = field(default_factory=list)  # profits for the next orders
    hold_results: bool = False
    order_failures: list[QuotexError] = field(default_factory=list)
    connect_failures: list[BaseException] = field(default_factory=list)
    connect_hangs: bool = False
    buy_delay_s: float = 0.0
    sent: list[SentOrder] = field(default_factory=list)
    prepared: list[tuple[str, int]] = field(default_factory=list)
    clients_made: int = 0
    clients_closed: int = 0
    account_changes: list[bool] = field(default_factory=list)
    in_flight: int = 0
    max_in_flight: int = 0
    _ids: Any = field(default_factory=lambda: count(1))

    def add_asset(self, symbol: str, **kwargs: Any) -> None:
        self.rows.append(make_row(symbol, **kwargs))

    def set_open(self, symbol: str, is_open: bool) -> None:
        for row in self.rows:
            if row[1] == symbol:
                row[14] = is_open


class ScriptedClient:
    def __init__(self, world: World) -> None:
        self.world = world
        world.clients_made += 1
        self._closed = False

    async def connect(self, *, demo: bool) -> None:
        if self.world.connect_hangs:
            await asyncio.sleep(3600)
        if self.world.connect_failures:
            raise self.world.connect_failures.pop(0)
        self.world.connected = True
        self.world.demo = demo

    async def warm_up(self) -> None:
        return None

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.world.clients_closed += 1
        self.world.connected = False

    def is_connected(self) -> bool:
        return self.world.connected and not self._closed

    def active_account_is_demo(self) -> bool:
        return self.world.demo

    async def change_account(self, *, demo: bool) -> None:
        self.world.account_changes.append(demo)
        self.world.demo = demo

    def balance_payload(self) -> dict[str, Any] | None:
        return self.world.balance

    def instruments(self) -> list[list[Any]]:
        return self.world.rows

    async def wait_for_balance(self, timeout_s: float) -> None:
        raise QuotexConnectionError("timed out waiting for the balance")

    async def prepare_asset(self, asset: str, duration_s: int, timeout_s: float) -> None:
        self.world.prepared.append((asset, duration_s))

    async def buy(
        self,
        asset: str,
        direction: Direction,
        duration_s: int,
        amount: Decimal,
        ack_timeout_s: float,
    ) -> str:
        self.world.in_flight += 1
        self.world.max_in_flight = max(self.world.max_in_flight, self.world.in_flight)
        try:
            if self.world.buy_delay_s:
                await asyncio.sleep(self.world.buy_delay_s)
            if self.world.order_failures:
                raise self.world.order_failures.pop(0)
            order_id = f"order-{next(self.world._ids)}"
            profit = (
                self.world.results.pop(0)
                if self.world.results
                else (amount * Decimal("0.85")).quantize(Decimal("0.01"))
            )
            self.world.sent.append(
                SentOrder(order_id, asset, direction, duration_s, amount, profit)
            )
            return order_id
        finally:
            self.world.in_flight -= 1

    async def wait_result(self, order_id: str, timeout_s: float) -> Decimal:
        order = next((o for o in self.world.sent if o.order_id == order_id), None)
        if order is None or self.world.hold_results:
            await asyncio.sleep(timeout_s)
            raise ResultTimeoutError(f"order {order_id} did not settle within {timeout_s:g}s")
        return order.profit
