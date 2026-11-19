"""The Deriv adapter (decisions D-74 to D-77): the same interface as the Quotex one, on Deriv's
official API.

- **Login:** a one-time link from `DerivLogin` (a token and an app id), then the socket. The
  account is checked on every connect: the demo slot must land on a demo account and the real slot
  on a real one, or nothing is used.
- **Reads from memory:** the balance (a subscription), which assets are open (`active_symbols`,
  refreshed every few minutes), the payout of each prepared asset and trade length (a price quote,
  refreshed every 30 s: Deriv does not stream Rise/Fall quotes on every index).
- **Orders** are not serialised (unlike D-27 on Quotex): each `buy` waits for its own reply. No
  reply in time means the order *may* exist (`OrderAckTimeoutError`), never a retry.
- **Results** come from a `proposal_open_contract` subscription; after a reconnect it is made
  again, so a contract that ended while the socket was down is still reported. A wait for a result
  never retries on a socket it already saw closed: it waits for the next connection (decision D-78;
  the engine froze on 2026-11-18 when a closed socket was retried in a loop that never yielded).
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from app.brokers.base import (
    AssetOffer,
    BalanceSnapshot,
    ConnectionState,
    OrderAck,
    TradeResult,
    classify_profit,
    validate_order,
)
from app.brokers.errors import (
    AccountMismatchError,
    AssetClosedError,
    BrokerConnectionError,
    BrokerError,
    DurationNotOfferedError,
    LoginRejectedError,
    NotConnectedError,
    OrderAckTimeoutError,
    OrderRejectedError,
    RealAccountNotAllowedError,
    ResultTimeoutError,
)
from app.core.backoff import BackoffPolicy, backoff_delay
from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.deriv.connection import ConnectionLostError, DerivConnection, Message
from app.deriv.protocol import (
    DerivAsset,
    LengthRange,
    allows,
    deriv_symbol,
    describe_lengths,
    duration_params,
    error_of,
    human_length,
    is_rise_fall,
    login_kind,
    parse_active_symbols,
    payout_percent,
    rise_fall_lengths,
    settled_profit,
    to_money,
)
from app.domain.enums import AccountType, Broker, Direction
from app.domain.ids import new_id
from app.domain.records import BalanceSnapshotRecord
from app.events.bus import EventBus
from app.events.types import BalanceUpdated, ConnectionChanged

log = structlog.get_logger()

type SocketUrl = Callable[[AccountType], Awaitable[str]]
type Sleep = Callable[[float], Awaitable[None]]

# A reference stake for the price quotes the payout percent is read from.
REFERENCE_STAKE = Decimal("10.00")
# How long a wait for a result pauses before it looks at the connection again, when the one it had
# answered nothing in time (the same socket is then tried again).
RESULT_RETRY_PAUSE_S = 0.5
_CONTRACT = {Direction.CALL: "CALL", Direction.PUT: "PUT"}


class DerivAdapter:
    def __init__(
        self,
        socket_url: SocketUrl,
        *,
        tasks: TaskSupervisor,
        clock: Clock,
        bus: EventBus | None = None,
        account_type: AccountType = AccountType.DEMO,
        allow_real: bool = False,
        real_available: bool = False,
        ack_timeout_s: float = 10.0,
        connect_timeout_s: float = 30.0,
        backoff: BackoffPolicy | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: Callable[[], float] = random.random,
        monitor_interval_s: float = 1.0,
        ping_interval_s: float = 30.0,
        payout_refresh_s: float = 30.0,
        assets_refresh_s: float = 300.0,
        preload_lengths: bool = True,
        lengths_per_tick: int = 5,
    ) -> None:
        if account_type is AccountType.REAL and not allow_real:
            raise RealAccountNotAllowedError("real trading is not enabled")
        self._socket_url = socket_url
        self._tasks = tasks
        self._clock = clock
        self._bus = bus
        self._account_type = account_type
        self._allow_real = allow_real
        self._real_available = real_available
        self._ack_timeout_s = ack_timeout_s
        self._connect_timeout_s = connect_timeout_s
        self._backoff = backoff or BackoffPolicy()
        self._sleep = sleep
        self._rng = rng
        self._monitor_interval_s = monitor_interval_s
        self._ping_interval_s = ping_interval_s
        self._payout_refresh_s = payout_refresh_s
        self._assets_refresh_s = assets_refresh_s
        self._preload_lengths = preload_lengths
        self._lengths_per_tick = lengths_per_tick

        self._state = ConnectionState.DISCONNECTED
        self._up = asyncio.Event()
        self._conn: DerivConnection | None = None
        self._connected_as: AccountType | None = None
        self._connected_since: datetime | None = None
        self._login_problem: str | None = None
        self._wanted = False
        self._monitor: asyncio.Task[None] | None = None
        self._currency = ""
        self._balance: Decimal | None = None
        self._assets: dict[str, DerivAsset] = {}
        self._lengths: dict[str, list[LengthRange] | None] = {}
        self._lengths_tried: set[str] = set()  # asked for in the background, on this connection
        self._payouts: dict[tuple[str, int], int] = {}  # (symbol, minutes) -> percent
        self._prepared: set[tuple[str, int]] = set()  # (symbol, seconds), on this connection
        self._wanted_quotes: set[tuple[str, int]] = set()  # made again after a reconnect
        self._last_ping = self._last_quotes = self._last_assets = 0.0

    # ---- state -------------------------------------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def account_type(self) -> AccountType:
        return self._account_type

    @property
    def connected_since(self) -> datetime | None:
        return self._connected_since

    @property
    def login_problem(self) -> str | None:
        return self._login_problem

    @property
    def currency(self) -> str:
        """The account's currency (orders are in it), known once connected."""
        return self._currency

    def _set_state(self, state: ConnectionState, detail: str | None = None) -> None:
        if state is ConnectionState.CONNECTED:
            self._up.set()
        else:
            self._up.clear()
        if state is self._state and detail is None:
            return
        changed = state is not self._state
        self._state = state
        log.info("deriv_state", state=state.value, detail=detail)
        if changed and self._bus is not None:
            self._bus.publish(
                ConnectionChanged(
                    occurred_at=self._clock.now(),
                    component="deriv",
                    connected=state is ConnectionState.CONNECTED,
                    detail=detail or state.value,
                )
            )

    # ---- connection life cycle ---------------------------------------------------------------

    async def connect(self, *, retry_forever: bool = False) -> None:
        if self._monitor is not None:
            return
        self._wanted = True
        self._login_problem = None
        self._set_state(ConnectionState.CONNECTING)
        attempt = 0
        while True:
            try:
                await self._establish()
                break
            except BrokerConnectionError as exc:
                if not retry_forever or not self._wanted or isinstance(exc, LoginRejectedError):
                    self._wanted = False
                    if isinstance(exc, LoginRejectedError):
                        self._login_problem = str(exc)
                    self._set_state(ConnectionState.DISCONNECTED, str(exc))
                    raise
                delay = backoff_delay(attempt, self._backoff, self._rng)
                attempt += 1
                log.warning("deriv_connect_failed", attempt=attempt, retry_in_s=round(delay, 2))
                await self._sleep(delay)
        self._monitor = self._tasks.spawn(self._watch(), name="deriv_monitor")

    async def disconnect(self) -> None:
        self._wanted = False
        monitor, self._monitor = self._monitor, None
        if monitor is not None:
            monitor.cancel()
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(asyncio.gather(monitor, return_exceptions=True), 5.0)
        await self._drop_connection()
        self._set_state(ConnectionState.DISCONNECTED)

    async def _establish(self) -> None:
        """One attempt: a fresh link, the socket, the account check, the balance and the assets."""
        account_type = self._account_type
        conn: DerivConnection | None = None
        try:
            async with asyncio.timeout(self._connect_timeout_s):
                url = await self._socket_url(account_type)
                conn = await DerivConnection.open(
                    url,
                    spawn=lambda coro, name: self._tasks.spawn(coro, name=name),
                    timeout_s=self._connect_timeout_s,
                    on_lost=self._on_connection_lost,
                )
                balance = await conn.request(
                    {"balance": 1, "subscribe": 1},
                    timeout_s=self._ack_timeout_s,
                    on_update=self._on_balance,
                )
                self._check_account(balance, account_type)
                symbols = await conn.request(
                    {"active_symbols": "brief"}, timeout_s=self._ack_timeout_s
                )
                if (problem := error_of(symbols)) is not None:
                    raise BrokerConnectionError(f"Deriv did not list its assets: {problem[1]}")
                self._assets = parse_active_symbols(symbols.get("active_symbols"))
        except BaseException as exc:
            if conn is not None:
                await conn.close()
            if isinstance(exc, BrokerConnectionError | asyncio.CancelledError):
                raise
            if isinstance(exc, TimeoutError):
                raise BrokerConnectionError("Deriv did not answer in time") from exc
            if isinstance(exc, BrokerError):
                raise BrokerConnectionError(str(exc)) from exc
            if isinstance(exc, Exception):
                raise BrokerConnectionError(f"{type(exc).__name__}: {exc}") from exc
            raise
        self._conn = conn
        self._connected_as = account_type
        self._prepared.clear()
        self._payouts.clear()
        self._lengths.clear()
        self._lengths_tried.clear()
        self._last_ping = self._last_quotes = self._last_assets = self._seconds()
        self._connected_since = self._clock.now()
        self._set_state(ConnectionState.CONNECTED)
        for symbol, duration_s in sorted(self._wanted_quotes):
            with contextlib.suppress(BrokerError, TimeoutError):
                await self._prepare(conn, symbol, duration_s)

    def _check_account(self, reply: Message, account_type: AccountType) -> None:
        """Decision D-76: the demo slot must land on a virtual account, the real slot on a real
        one."""
        if (problem := error_of(reply)) is not None:
            code, message = problem
            if code in {"AuthorizationRequired", "InvalidToken", "PermissionDenied"}:
                raise LoginRejectedError(f"Deriv refused the login: {message}")
            raise BrokerConnectionError(f"Deriv did not give the balance: {message}")
        data = reply.get("balance")
        if not isinstance(data, Mapping):
            raise BrokerConnectionError("Deriv's balance answer has no balance")
        loginid = str(data.get("loginid") or "")
        kind = login_kind(loginid)
        if kind is None:
            # An account number we cannot read (Deriv's new numbering is not fully documented):
            # the account list and the link already said which kind it is, so it is not refused.
            log.info("deriv_account_number_unknown", loginid=loginid, wanted=account_type.value)
        elif kind is not account_type:
            raise LoginRejectedError(
                f"The {account_type.value} login opened account {loginid}, which is a "
                f"{kind.value} account; nothing will be traded on it."
            )
        self._on_balance(reply)

    async def _drop_connection(self) -> None:
        conn, self._conn = self._conn, None
        self._connected_as = None
        self._connected_since = None
        if conn is not None:
            await conn.close()

    def _on_connection_lost(self, conn: DerivConnection) -> None:
        """The socket in use closed: say so at once, so nothing waits on (or retries) a dead
        socket until the monitor notices it. The monitor then reconnects."""
        if conn is not self._conn or not self._wanted:
            return  # a socket being closed on purpose, or one that never went into use
        self._connected_since = None
        self._set_state(ConnectionState.RECONNECTING, "connection lost")

    async def _watch(self) -> None:
        """Notice a lost socket and reconnect; keep the socket alive; refresh what is read from
        memory."""
        while self._wanted:
            await asyncio.sleep(self._monitor_interval_s)
            try:
                conn = self._conn
                if conn is None or not conn.is_open:
                    await self._reconnect()
                else:
                    await self._housekeeping(conn)
            except Exception:
                log.error("deriv_monitor_error", exc_info=True)

    async def _housekeeping(self, conn: DerivConnection) -> None:
        now = self._seconds()
        if now - self._last_ping >= self._ping_interval_s:
            self._last_ping = now
            with contextlib.suppress(BrokerConnectionError, TimeoutError):
                await conn.request({"ping": 1}, timeout_s=self._ack_timeout_s)
        if now - self._last_quotes >= self._payout_refresh_s:
            self._last_quotes = now
            for symbol, duration_s in sorted(self._wanted_quotes):
                try:
                    self._payouts[(symbol, duration_s // 60)] = await self._quote(
                        conn, symbol, duration_s
                    )
                except (BrokerError, TimeoutError) as exc:
                    # Never trade on a stale figure: no payout means the signal is skipped.
                    self._payouts.pop((symbol, duration_s // 60), None)
                    log.warning("deriv_quote_failed", symbol=symbol, error=str(exc))
        if now - self._last_assets >= self._assets_refresh_s:
            self._last_assets = now
            with contextlib.suppress(BrokerError, TimeoutError):
                reply = await conn.request(
                    {"active_symbols": "brief"}, timeout_s=self._ack_timeout_s
                )
                if error_of(reply) is None:
                    self._assets = parse_active_symbols(reply.get("active_symbols"))
        if self._preload_lengths:
            await self._load_some_lengths(conn)

    async def _load_some_lengths(self, conn: DerivConnection) -> None:
        """Learn, a few assets per tick, the trade lengths every open asset allows, so a signal
        with a length Deriv does not offer is skipped from memory (`order_refusal`), never sent."""
        todo = [
            symbol
            for symbol, asset in sorted(self._assets.items())
            if asset.is_open and symbol not in self._lengths and symbol not in self._lengths_tried
        ][: self._lengths_per_tick]
        for symbol in todo:
            self._lengths_tried.add(symbol)
            with contextlib.suppress(BrokerError, TimeoutError):
                await self._lengths_for(conn, symbol)

    async def _reconnect(self) -> None:
        log.warning("deriv_connection_lost")
        self._set_state(ConnectionState.RECONNECTING, "connection lost")
        await self._drop_connection()
        attempt = 0
        while self._wanted:
            try:
                await self._establish()
                return
            except LoginRejectedError as exc:
                self._wanted = False  # a refused login does not get better by trying again
                self._login_problem = str(exc)
                self._set_state(ConnectionState.DISCONNECTED, str(exc))
                log.error("deriv_login_rejected", error=str(exc))
                return
            except BrokerConnectionError as exc:
                delay = backoff_delay(attempt, self._backoff, self._rng)
                attempt += 1
                log.warning(
                    "deriv_reconnect_failed",
                    attempt=attempt,
                    retry_in_s=round(delay, 2),
                    error=str(exc),
                )
                await self._sleep(delay)

    # ---- account -----------------------------------------------------------------------------

    def set_real_allowed(self, allowed: bool) -> None:
        self._allow_real = allowed

    async def set_account_type(self, account_type: AccountType) -> None:
        """Switching means a new link for the other account, so the socket is opened again."""
        if account_type is AccountType.REAL and not self._allow_real:
            raise RealAccountNotAllowedError("real trading is not enabled")
        if account_type is AccountType.REAL and not self._real_available:
            raise RealAccountNotAllowedError("no Deriv token for the real account is stored")
        if account_type is self._account_type:
            return
        self._account_type = account_type
        self._balance = None
        if self._conn is not None:
            await self._drop_connection()
            try:
                await self._establish()
            except BrokerConnectionError as exc:
                self._set_state(ConnectionState.RECONNECTING, str(exc))  # the monitor goes on

    def balance(self) -> BalanceSnapshot | None:
        if self._balance is None or self._state is not ConnectionState.CONNECTED:
            return None
        return BalanceSnapshot(self._account_type, self._balance, self._clock.now())

    async def refresh_balance(self) -> BalanceSnapshot:
        self._require_connection()
        snapshot = self.balance()
        if snapshot is None:
            raise NotConnectedError("Deriv did not provide a balance")
        return snapshot

    def _on_balance(self, message: Message) -> None:
        data = message.get("balance")
        if not isinstance(data, Mapping) or "balance" not in data:
            return
        self._currency = str(data.get("currency") or self._currency)
        amount = to_money(data["balance"])
        if amount == self._balance:
            return
        self._balance = amount
        if self._bus is not None:
            now = self._clock.now()
            self._bus.publish(
                BalanceUpdated(
                    occurred_at=now,
                    snapshot=BalanceSnapshotRecord(
                        id=new_id(),
                        taken_at=now,
                        account_type=self._account_type,
                        balance=amount,
                        broker=Broker.DERIV,
                    ),
                )
            )

    # ---- market data (memory only) -----------------------------------------------------------

    def payout(self, asset: str, minutes: int) -> int | None:
        symbol = deriv_symbol(asset)
        if symbol is None or self._state is not ConnectionState.CONNECTED:
            return None
        return self._payouts.get((symbol, minutes))

    def is_open(self, asset: str) -> bool:
        symbol = deriv_symbol(asset)
        known = self._assets.get(symbol) if symbol is not None else None
        return self._state is ConnectionState.CONNECTED and known is not None and known.is_open

    def order_refusal(self, asset: str, duration_s: int) -> str | None:
        """Why Deriv would surely refuse this order, from memory; None if nothing known says so
        (before the asset list or the asset's trade lengths are known, Deriv's answer decides)."""
        symbol = deriv_symbol(asset)
        if symbol is None:
            if asset.lower().endswith("_otc"):
                return f"{asset} is an OTC pair: Deriv has no OTC pairs"
            return f"{asset} is not traded on Deriv"
        if not self._assets:
            return None
        known = self._assets.get(symbol)
        if known is None:
            return f"{asset} is not traded on Deriv"
        if not known.is_open:
            return f"{asset} is closed on Deriv"
        if symbol in self._lengths:
            lengths = self._lengths[symbol]
            if not allows(lengths, duration_s):
                return (
                    f"Deriv does not offer {human_length(duration_s)} Rise/Fall on {asset}: it "
                    f"offers {describe_lengths(lengths or [])}"
                )
        return None

    def catalogue(self) -> list[AssetOffer]:
        """Every asset Deriv listed, with the Rise/Fall lengths learnt so far (None: not yet)."""
        return [
            AssetOffer(
                asset=a.asset,
                name=a.display_name,
                market=a.market,
                is_open=a.is_open,
                lengths=None
                if (ranges := self._lengths.get(a.symbol)) is None
                else tuple((r.min_s, r.max_s) for r in ranges),
            )
            for a in self.assets()
        ]

    def assets(self) -> list[DerivAsset]:
        """Every asset Deriv listed, open or not (for the dashboard and the check script)."""
        return sorted(self._assets.values(), key=lambda a: (a.market, a.asset))

    async def rise_fall_offer(self, asset: str) -> list[Mapping[str, Any]]:
        """Deriv's own Rise/Fall entries for an asset, as sent (for the check script)."""
        conn = self._require_connection()
        symbol = self._known_symbol(asset)
        return [entry for entry in await self._contracts_for(conn, symbol) if is_rise_fall(entry)]

    async def contracts_reply(self, asset: str) -> Message:
        """Deriv's whole `contracts_for` answer for an asset, unfiltered (for the check script)."""
        conn = self._require_connection()
        symbol = self._known_symbol(asset)
        return await conn.request({"contracts_for": symbol}, timeout_s=self._ack_timeout_s)

    async def trade_lengths(self, asset: str) -> list[LengthRange] | None:
        """The trade lengths Rise/Fall allows on the asset (None: Deriv's answer is unreadable)."""
        conn = self._require_connection()
        return await self._lengths_for(conn, self._known_symbol(asset))

    async def prepare_asset(self, asset: str, duration_s: int) -> None:
        """Check the trade length is offered and read the payout, once per asset and length."""
        conn = self._require_connection()
        symbol = self._known_symbol(asset)
        if (symbol, duration_s) not in self._prepared:
            await self._prepare(conn, symbol, duration_s, asset=asset)

    async def _prepare(
        self, conn: DerivConnection, symbol: str, duration_s: int, *, asset: str | None = None
    ) -> None:
        lengths = await self._lengths_for(conn, symbol)
        if not allows(lengths, duration_s):
            raise DurationNotOfferedError(
                f"Deriv does not offer {duration_s} s Rise/Fall on {asset or symbol} (it offers "
                f"{describe_lengths(lengths or [])}); order not sent"
            )
        self._payouts[(symbol, duration_s // 60)] = await self._quote(conn, symbol, duration_s)
        self._prepared.add((symbol, duration_s))
        self._wanted_quotes.add((symbol, duration_s))

    async def _contracts_for(self, conn: DerivConnection, symbol: str) -> list[Mapping[str, Any]]:
        reply = await conn.request({"contracts_for": symbol}, timeout_s=self._ack_timeout_s)
        if (problem := error_of(reply)) is not None:
            raise AssetClosedError(f"Deriv has no contracts on {symbol}: {problem[1]}")
        offer = reply.get("contracts_for")
        available = offer.get("available") if isinstance(offer, Mapping) else None
        if not isinstance(available, list):
            return []
        return [entry for entry in available if isinstance(entry, Mapping)]

    async def _lengths_for(self, conn: DerivConnection, symbol: str) -> list[LengthRange] | None:
        if symbol not in self._lengths:
            self._lengths[symbol] = rise_fall_lengths(await self._contracts_for(conn, symbol))
        return self._lengths[symbol]

    async def _quote(self, conn: DerivConnection, symbol: str, duration_s: int) -> int:
        duration, unit = duration_params(duration_s)
        reply = await conn.request(
            {
                "proposal": 1,
                "amount": float(REFERENCE_STAKE),
                "basis": "stake",
                "contract_type": "CALL",
                "currency": self._currency,
                "duration": duration,
                "duration_unit": unit,
                "underlying_symbol": symbol,
            },
            timeout_s=self._ack_timeout_s,
        )
        if (problem := error_of(reply)) is not None:
            raise OrderRejectedError(f"Deriv would not price {symbol}: {problem[1]}")
        quote = reply.get("proposal")
        if not isinstance(quote, Mapping):
            raise OrderRejectedError(f"Deriv sent no price for {symbol}")
        return payout_percent(quote.get("ask_price"), quote.get("payout"))

    # ---- trading -----------------------------------------------------------------------------

    async def place_order(
        self, asset: str, direction: Direction, duration_s: int, amount: Decimal
    ) -> OrderAck:
        validate_order(direction, duration_s, amount)
        conn = self._require_connection()
        if self._connected_as is not self._account_type:
            raise AccountMismatchError(
                f"adapter is set to {self._account_type.value} but the connection is on the other "
                "account; order not sent"
            )
        if not self.is_open(asset):
            raise AssetClosedError(f"{asset} is unknown or closed on Deriv; order not sent")
        symbol = self._known_symbol(asset)
        await self.prepare_asset(asset, duration_s)  # a no-op after the first order of this kind
        duration, unit = duration_params(duration_s)
        stake = float(amount)
        order = {
            "buy": "1",
            "price": stake,
            "parameters": {
                "amount": stake,
                "basis": "stake",
                "contract_type": _CONTRACT[direction],
                "currency": self._currency,
                "duration": duration,
                "duration_unit": unit,
                "underlying_symbol": symbol,
            },
        }
        t_sent = self._clock.monotonic_ns()
        try:
            reply = await conn.request(order, timeout_s=self._ack_timeout_s)
        except (TimeoutError, ConnectionLostError) as exc:
            raise OrderAckTimeoutError(
                f"no confirmation from Deriv within {self._ack_timeout_s:g}s; "
                "the order may have been placed"
            ) from exc
        t_acked = self._clock.monotonic_ns()
        if (problem := error_of(reply)) is not None:
            raise OrderRejectedError(f"{problem[1]} ({problem[0]})")
        bought = reply.get("buy")
        contract_id = bought.get("contract_id") if isinstance(bought, Mapping) else None
        if contract_id is None:
            raise OrderRejectedError("Deriv confirmed the order without a contract id")
        return OrderAck(order_id=str(contract_id), t_order_sent_ns=t_sent, t_order_acked_ns=t_acked)

    async def await_result(self, order_id: str, timeout_s: float) -> TradeResult:
        self._require_connection()
        if not order_id.isdigit():
            raise ResultTimeoutError(f"{order_id!r} is not a Deriv contract id")
        try:
            async with asyncio.timeout(timeout_s):
                dead: DerivConnection | None = None
                while True:
                    conn = await self._connection_other_than(dead)
                    try:
                        profit = await self._follow_contract(conn, int(order_id))
                    except (ConnectionLostError, NotConnectedError):
                        dead = conn  # follow it again on the next connection, never on this one
                        continue
                    except TimeoutError:
                        await asyncio.sleep(RESULT_RETRY_PAUSE_S)  # no answer: ask again
                        continue
                    return TradeResult(order_id, classify_profit(profit), profit)
        except TimeoutError as exc:
            raise ResultTimeoutError(
                f"order {order_id} did not settle within {timeout_s:g}s"
            ) from exc

    async def _connection_other_than(self, dead: DerivConnection | None) -> DerivConnection:
        """The open connection to use, never `dead`. Every way round this loop waits (for the
        adapter to be up, or a pause), so it can never keep the event loop to itself."""
        while True:
            await self._up.wait()
            conn = self._conn
            if conn is not None and conn is not dead and conn.is_open:
                return conn
            await asyncio.sleep(RESULT_RETRY_PAUSE_S)

    async def _follow_contract(self, conn: DerivConnection, contract_id: int) -> Decimal:
        settled: asyncio.Future[Decimal] = asyncio.get_running_loop().create_future()

        def on_update(message: Message) -> None:
            contract = message.get("proposal_open_contract")
            if isinstance(contract, Mapping) and not settled.done():
                try:
                    profit = settled_profit(contract)
                except BrokerError as exc:
                    settled.set_exception(exc)
                    return
                if profit is not None:
                    settled.set_result(profit)

        first = await conn.request(
            {"proposal_open_contract": 1, "contract_id": contract_id, "subscribe": 1},
            timeout_s=self._ack_timeout_s,
            on_update=on_update,
        )
        try:
            if (problem := error_of(first)) is not None:
                raise ResultTimeoutError(
                    f"Deriv could not report contract {contract_id}: {problem[1]}"
                )
            on_update(first)
            closed = asyncio.ensure_future(conn.wait_closed())
            try:
                watched: set[asyncio.Future[Any]] = {settled, closed}
                await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
            finally:
                closed.cancel()
            if not settled.done():
                raise ConnectionLostError("the connection to Deriv was lost")
            return settled.result()
        finally:
            if not settled.done():
                settled.cancel()
            self._tasks.spawn(conn.forget(first), name="deriv_forget")

    # ---- helpers -----------------------------------------------------------------------------

    def _seconds(self) -> float:
        return self._clock.monotonic_ns() / 1e9

    def _require_connection(self) -> DerivConnection:
        conn = self._conn
        if conn is None or self._state is not ConnectionState.CONNECTED:
            raise NotConnectedError(f"not connected to Deriv (state: {self._state.value})")
        return conn

    def _known_symbol(self, asset: str) -> str:
        symbol = deriv_symbol(asset)
        if symbol is None or symbol not in self._assets:
            raise AssetClosedError(f"{asset} is not traded on Deriv; order not sent")
        return symbol
