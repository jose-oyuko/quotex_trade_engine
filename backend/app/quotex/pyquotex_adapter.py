"""The real Quotex adapter: all the decisions, none of the library details.

It owns the connection life cycle (connect, watch, reconnect with backoff), the safety checks
(account must match, asset must be open, amounts must be sane) and the in-memory reads the hot path
relies on. It reaches Quotex only through `QuotexClient` (see client.py).

Things worth knowing:
- Orders are sent **one at a time**: pyquotex has a single shared "order confirmed" slot, so two
  orders in flight at once could be handed each other's confirmation. The lock covers send to
  confirmation only (normally tens to a few hundred milliseconds), never the wait for the result.
- Results are awaited by event, never by sleeping (D-13).
- Nothing here blocks the event loop and no database is touched (D-4, D-14).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from decimal import Decimal

import structlog

from app.core.backoff import BackoffPolicy, backoff_delay
from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.domain.enums import AccountType, Direction
from app.domain.ids import new_id
from app.domain.records import BalanceSnapshotRecord
from app.events.bus import EventBus
from app.events.types import BalanceUpdated, ConnectionChanged
from app.quotex.base import (
    BalanceSnapshot,
    ConnectionState,
    OrderAck,
    TradeResult,
    classify_profit,
    validate_order,
)
from app.quotex.client import QuotexClient
from app.quotex.errors import (
    AccountMismatchError,
    AssetClosedError,
    NotConnectedError,
    QuotexConnectionError,
    RealAccountNotAllowedError,
)
from app.quotex.parsing import (
    balance_from_payload,
    find_instrument,
    instrument_is_open,
    instrument_payout,
)

log = structlog.get_logger()

Sleep = Callable[[float], Awaitable[None]]


class PyQuotexAdapter:
    def __init__(
        self,
        client_factory: Callable[[], QuotexClient],
        *,
        tasks: TaskSupervisor,
        clock: Clock,
        bus: EventBus | None = None,
        account_type: AccountType = AccountType.DEMO,
        allow_real: bool = False,
        backoff: BackoffPolicy | None = None,
        connect_timeout_s: float = 45.0,
        ack_timeout_s: float = 10.0,
        monitor_interval_s: float = 1.0,
        sleep: Sleep = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        if account_type is AccountType.REAL and not allow_real:
            raise RealAccountNotAllowedError("real trading is not enabled")
        self._client_factory = client_factory
        self._tasks = tasks
        self._clock = clock
        self._bus = bus
        self._account_type = account_type
        self._allow_real = allow_real
        self._backoff = backoff or BackoffPolicy()
        self._connect_timeout_s = connect_timeout_s
        self._ack_timeout_s = ack_timeout_s
        self._monitor_interval_s = monitor_interval_s
        self._sleep = sleep
        self._rng = rng

        self._state = ConnectionState.DISCONNECTED
        self._client: QuotexClient | None = None
        self._wanted = False
        self._monitor: asyncio.Task[None] | None = None
        self._order_lock = asyncio.Lock()
        self._prepared: set[tuple[str, int]] = set()
        self._last_published_balance: Decimal | None = None

    # ---- state -------------------------------------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def account_type(self) -> AccountType:
        return self._account_type

    def _set_state(self, state: ConnectionState, detail: str | None = None) -> None:
        if state is self._state and detail is None:
            return
        changed = state is not self._state
        self._state = state
        log.info("quotex_state", state=state.value, detail=detail)
        if changed and self._bus is not None:
            self._bus.publish(
                ConnectionChanged(
                    occurred_at=self._clock.now(),
                    component="quotex",
                    connected=state is ConnectionState.CONNECTED,
                    detail=detail or state.value,
                )
            )

    # ---- connection life cycle ---------------------------------------------------------------

    async def connect(self, *, retry_forever: bool = False) -> None:
        if self._monitor is not None:
            return
        self._wanted = True
        self._set_state(ConnectionState.CONNECTING)
        attempt = 0
        while True:
            try:
                await self._establish()
                break
            except QuotexConnectionError as exc:
                if not retry_forever or not self._wanted:
                    self._wanted = False
                    self._set_state(ConnectionState.DISCONNECTED, str(exc))
                    raise
                delay = backoff_delay(attempt, self._backoff, self._rng)
                attempt += 1
                log.warning("quotex_connect_failed", attempt=attempt, retry_in_s=round(delay, 2))
                await self._sleep(delay)
        self._monitor = self._tasks.spawn(self._watch(), name="quotex_monitor")

    async def disconnect(self) -> None:
        self._wanted = False
        monitor, self._monitor = self._monitor, None
        if monitor is not None:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        await self._drop_client()
        self._set_state(ConnectionState.DISCONNECTED)

    async def _establish(self) -> None:
        """One connection attempt: new client, log in, warm up. Raises QuotexConnectionError."""
        client = self._client_factory()
        try:
            async with asyncio.timeout(self._connect_timeout_s):
                await client.connect(demo=self._account_type is AccountType.DEMO)
                await client.warm_up()
        except BaseException as exc:
            await _close_quietly(client)
            if isinstance(exc, QuotexConnectionError | asyncio.CancelledError):
                raise
            if isinstance(exc, Exception):
                raise QuotexConnectionError(f"{type(exc).__name__}: {exc}") from exc
            raise
        self._client = client
        self._prepared.clear()
        self._set_state(ConnectionState.CONNECTED)

    async def _drop_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await _close_quietly(client)

    async def _watch(self) -> None:
        """Notice a lost connection, reconnect with backoff, and publish balance changes."""
        while self._wanted:
            await asyncio.sleep(self._monitor_interval_s)
            try:
                client = self._client
                if client is None or not client.is_connected():
                    await self._reconnect()
                else:
                    self._publish_balance_if_changed()
            except Exception:
                log.error("quotex_monitor_error", exc_info=True)

    async def _reconnect(self) -> None:
        log.warning("quotex_connection_lost")
        self._set_state(ConnectionState.RECONNECTING, "connection lost")
        await self._drop_client()
        attempt = 0
        while self._wanted:
            try:
                await self._establish()
                return
            except QuotexConnectionError as exc:
                delay = backoff_delay(attempt, self._backoff, self._rng)
                attempt += 1
                log.warning(
                    "quotex_reconnect_failed",
                    attempt=attempt,
                    retry_in_s=round(delay, 2),
                    error=str(exc),
                )
                await self._sleep(delay)

    # ---- account -----------------------------------------------------------------------------

    async def set_account_type(self, account_type: AccountType) -> None:
        if account_type is AccountType.REAL and not self._allow_real:
            raise RealAccountNotAllowedError("real trading is not enabled")
        if account_type is self._account_type:
            return
        client = self._client
        if client is not None:
            await client.change_account(demo=account_type is AccountType.DEMO)
        self._account_type = account_type
        self._last_published_balance = None

    def balance(self) -> BalanceSnapshot | None:
        client = self._client
        if client is None:
            return None
        amount = balance_from_payload(client.balance_payload(), self._account_type)
        if amount is None:
            return None
        return BalanceSnapshot(self._account_type, amount, self._clock.now())

    async def refresh_balance(self) -> BalanceSnapshot:
        client = self._require_client()
        snapshot = self.balance()
        if snapshot is None:
            await client.wait_for_balance(self._ack_timeout_s)
            snapshot = self.balance()
        if snapshot is None:
            raise QuotexConnectionError("Quotex did not provide a balance")
        return snapshot

    def _publish_balance_if_changed(self) -> None:
        snapshot = self.balance()
        if snapshot is None or snapshot.balance == self._last_published_balance:
            return
        self._last_published_balance = snapshot.balance
        if self._bus is not None:
            self._bus.publish(
                BalanceUpdated(
                    occurred_at=snapshot.taken_at,
                    snapshot=BalanceSnapshotRecord(
                        id=new_id(),
                        taken_at=snapshot.taken_at,
                        account_type=snapshot.account_type,
                        balance=snapshot.balance,
                    ),
                )
            )

    # ---- market data (memory only) -----------------------------------------------------------

    def payout(self, asset: str, minutes: int) -> int | None:
        client = self._client
        if client is None:
            return None
        row = find_instrument(client.instruments(), asset)
        return None if row is None else instrument_payout(row, minutes)

    def is_open(self, asset: str) -> bool:
        client = self._client
        if client is None:
            return False
        row = find_instrument(client.instruments(), asset)
        return row is not None and instrument_is_open(row)

    async def prepare_asset(self, asset: str, duration_s: int) -> None:
        client = self._require_client()
        key = (asset, duration_s)
        if key in self._prepared:
            return
        await client.prepare_asset(asset, duration_s, self._ack_timeout_s)
        self._prepared.add(key)

    # ---- trading -----------------------------------------------------------------------------

    async def place_order(
        self, asset: str, direction: Direction, duration_s: int, amount: Decimal
    ) -> OrderAck:
        validate_order(direction, duration_s, amount)
        client = self._require_client()
        if client.active_account_is_demo() != (self._account_type is AccountType.DEMO):
            raise AccountMismatchError(
                f"adapter is set to {self._account_type.value} but the connection is on the other "
                "account; order not sent"
            )
        if not self.is_open(asset):
            raise AssetClosedError(f"{asset} is unknown or closed; order not sent")
        await self.prepare_asset(asset, duration_s)  # no-op after the first order for this asset

        async with self._order_lock:
            t_sent = self._clock.monotonic_ns()
            order_id = await client.buy(asset, direction, duration_s, amount, self._ack_timeout_s)
            t_acked = self._clock.monotonic_ns()
        return OrderAck(order_id=order_id, t_order_sent_ns=t_sent, t_order_acked_ns=t_acked)

    async def await_result(self, order_id: str, timeout_s: float) -> TradeResult:
        client = self._require_client()
        profit = await client.wait_result(order_id, timeout_s)
        return TradeResult(order_id=order_id, outcome=classify_profit(profit), profit=profit)

    # ---- helpers -----------------------------------------------------------------------------

    def _require_client(self) -> QuotexClient:
        client = self._client
        if client is None or self._state is not ConnectionState.CONNECTED:
            raise NotConnectedError(f"not connected to Quotex (state: {self._state.value})")
        return client


async def _close_quietly(client: QuotexClient) -> None:
    try:
        await client.close()
    except Exception:
        log.warning("quotex_client_close_failed", exc_info=True)
