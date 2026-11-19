"""A local stand-in for Deriv's trading socket, for driving the real `DerivAdapter` offline.

It speaks the messages the adapter uses, in the shapes of Deriv's published JSON schemas
(`balance`, `active_symbols`, `contracts_for`, `proposal`, `buy`, `proposal_open_contract`, `ping`,
`forget`), echoes `req_id` and gives subscriptions an id. What it proves: the adapter's matching,
subscriptions, timeouts, reconnects and checks work over a real WebSocket. What it cannot prove:
that Deriv answers exactly like this; that is `npm run deriv:check`'s job.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import count
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from app.domain.enums import AccountType


def rise_fall(low: str, high: str, *, expiry: str = "intraday") -> dict[str, Any]:
    """A Rise/Fall entry of `contracts_for` as the live demo sends it (2026-11-17): one barrier, the
    entry price."""
    return {
        "barriers": 1,
        "contract_category": "callput",
        "contract_type": "CALL",
        "expiry_type": expiry,
        "min_contract_duration": low,
        "max_contract_duration": high,
        "sentiment": "up",
    }


def higher_lower(low: str, high: str) -> dict[str, Any]:
    return {
        **rise_fall(low, high),
        "contract_category": "higherlower",
        "contract_type": "HIGHER",
    }


@dataclass
class Contract:
    contract_id: int
    symbol: str
    contract_type: str
    stake: Decimal
    profit: Decimal | None = None  # None while open
    planned: Decimal | None = None  # the scripted result, fixed when it was bought
    entry_spot: Decimal | None = None  # set by `set_terms`, as Deriv does after the first tick
    date_expiry: int | None = None
    payout: Decimal | None = None
    exit_spot: Decimal | None = None  # set by `expire`, as Deriv does just after the end time

    def state(self) -> dict[str, Any]:
        settled = self.profit is not None
        expired = settled or self.exit_spot is not None
        state: dict[str, Any] = {
            "contract_id": self.contract_id,
            "underlying_symbol": self.symbol,
            "contract_type": self.contract_type,
            "buy_price": f"{self.stake:.2f}",
            "is_sold": 1 if settled else 0,
            "is_expired": 1 if expired else 0,
            "status": ("won" if self.profit and self.profit > 0 else "lost") if settled else "open",
            "profit": f"{self.profit:.2f}" if settled else "0.00",
        }
        if self.payout is not None:
            state["payout"] = float(self.payout)
        if self.entry_spot is not None:  # the live API's names (seen on the demo, 2026-11-19)
            state["entry_spot"] = f"{self.entry_spot}"
        if self.exit_spot is not None:
            state["exit_spot"] = f"{self.exit_spot}"
        if self.date_expiry is not None:
            state["date_expiry"] = self.date_expiry
        return state


@dataclass
class FakeDerivServer:
    assets: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "underlying_symbol": "frxEURUSD",
                "underlying_symbol_name": "EUR/USD",
                "market": "forex",
                "exchange_is_open": 1,
                "is_trading_suspended": 0,
            },
            {
                "underlying_symbol": "R_75",
                "underlying_symbol_name": "Volatility 75 Index",
                "market": "synthetic_index",
                "exchange_is_open": 1,
                "is_trading_suspended": 0,
            },
            {
                "underlying_symbol": "frxAUDUSD",
                "underlying_symbol_name": "AUD/USD",
                "market": "forex",
                "exchange_is_open": 0,
                "is_trading_suspended": 0,
            },
        ]
    )
    offers: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {
            "frxEURUSD": [rise_fall("15m", "365d"), higher_lower("1d", "365d")],
            "R_75": [rise_fall("1t", "10t", expiry="tick"), rise_fall("15s", "1d")],
            "frxAUDUSD": [rise_fall("15m", "365d")],
        }
    )
    payouts: dict[str, int] = field(default_factory=lambda: {"frxEURUSD": 80, "R_75": 95})
    balances: dict[AccountType, Decimal] = field(
        default_factory=lambda: {
            AccountType.DEMO: Decimal("10000.00"),
            AccountType.REAL: Decimal("50.00"),
        }
    )
    loginids: dict[AccountType, str] = field(
        default_factory=lambda: {AccountType.DEMO: "VRTC1001", AccountType.REAL: "CR2002"}
    )
    currency: str = "USD"
    profits: list[Decimal] = field(default_factory=list)  # next results; default a win
    settle_after_s: float | None = 0.02  # None: never settle until `settle(id)`
    answer_orders: bool = True  # False: a `buy` gets no reply at all
    reverse_orders: int = 0  # hold this many `buy` replies, then answer them in reverse order
    buy_errors: list[dict[str, str]] = field(default_factory=list)
    proposal_errors: dict[str, dict[str, str]] = field(default_factory=dict)  # by symbol
    stream_req_id: bool = True  # False: updates carry only `subscription.id`

    received: list[dict[str, Any]] = field(default_factory=list)
    contracts: dict[int, Contract] = field(default_factory=dict)
    links_used: list[str] = field(default_factory=list)
    connections: int = 0

    _server: Any = None
    _port: int = 0
    _ids: Any = field(default_factory=lambda: count(5001))
    _clients: set[ServerConnection] = field(default_factory=set)
    _held: list[tuple[ServerConnection, dict[str, Any]]] = field(default_factory=list)
    _watchers: dict[int, list[tuple[ServerConnection, int, str]]] = field(default_factory=dict)
    _balance_streams: list[tuple[ServerConnection, int, str, AccountType]] = field(
        default_factory=list
    )
    _tick_streams: dict[str, list[tuple[ServerConnection, int, str]]] = field(default_factory=dict)

    async def start(self) -> None:
        self._server = await serve(self._handle, "127.0.0.1", 0)
        self._port = next(iter(self._server.sockets)).getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def link(self, kind: AccountType) -> str:
        """What `DerivLogin.socket_url` returns: a fresh one-time link to the socket."""
        return f"ws://127.0.0.1:{self._port}/ws/{kind.value}?otp={uuid.uuid4().hex}"

    async def drop_clients(self) -> None:
        for client in list(self._clients):
            await client.close()

    async def drop_clients_with_a_restart(self) -> None:
        """What Deriv's proxy did on 2026-11-18: close every socket with 1001 (going away)."""
        for client in list(self._clients):
            await client.close(code=1001, reason="CloudFlare WebSocket proxy restarting")

    def cut_clients(self) -> None:
        """The network goes away: the sockets die without a closing handshake."""
        for client in list(self._clients):
            client.transport.abort()

    def sent(self, name: str) -> list[dict[str, Any]]:
        return [message for message in self.received if name in message]

    async def set_terms(
        self, contract_id: int, *, entry: Decimal, expiry: int, payout: Decimal | None = None
    ) -> None:
        """What Deriv says once the contract started: its entry tick, end time and payout."""
        contract = self.contracts[contract_id]
        contract.entry_spot, contract.date_expiry = entry, expiry
        contract.payout = payout if payout is not None else contract.stake * Decimal("1.95")
        await self._push_contract(contract, keep_watching=True)

    async def expire(self, contract_id: int, exit_spot: Decimal) -> None:
        """The update Deriv sends just after the end time: expired, its exit price, not sold yet."""
        contract = self.contracts[contract_id]
        contract.exit_spot = exit_spot
        await self._push_contract(contract, keep_watching=True)

    async def push_tick(self, symbol: str, epoch: int, quote: Decimal) -> None:
        """A price tick of `symbol`, to every subscriber of its `ticks` stream."""
        for ws, req_id, sub in list(self._tick_streams.get(symbol, [])):
            await self._send(
                ws,
                {
                    "msg_type": "tick",
                    "req_id": req_id,
                    "tick": {"symbol": symbol, "epoch": epoch, "quote": float(quote)},
                    "subscription": {"id": sub},
                },
            )

    async def settle(self, contract_id: int, profit: Decimal | None = None) -> None:
        contract = self.contracts[contract_id]
        if contract.profit is None:
            contract.profit = profit if profit is not None else contract.planned
            await self._after_settle(contract)

    # ---- protocol ----------------------------------------------------------------------------

    async def _handle(self, ws: ServerConnection) -> None:
        path = ws.request.path if ws.request is not None else ""
        if path in self.links_used:
            await ws.close(code=4001, reason="one-time code already used")
            return
        self.links_used.append(path)
        kind = AccountType.REAL if path.startswith("/ws/real") else AccountType.DEMO
        self.connections += 1
        self._clients.add(ws)
        try:
            async for frame in ws:
                message = json.loads(frame)
                self.received.append(message)
                await self._answer(ws, kind, message)
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)

    async def _send(self, ws: ServerConnection, message: dict[str, Any]) -> None:
        with contextlib.suppress(ConnectionClosed):
            await ws.send(json.dumps(message))

    async def _answer(self, ws: ServerConnection, kind: AccountType, msg: dict[str, Any]) -> None:
        req_id = msg.get("req_id")
        base = {"echo_req": msg, "req_id": req_id}
        if "balance" in msg:
            sub = uuid.uuid4().hex
            self._balance_streams.append((ws, req_id, sub, kind))
            await self._send(
                ws,
                {
                    **base,
                    "msg_type": "balance",
                    "balance": self._balance(kind, sub),
                    "subscription": {"id": sub},
                },
            )
        elif "active_symbols" in msg:
            await self._send(
                ws, {**base, "msg_type": "active_symbols", "active_symbols": self.assets}
            )
        elif "contracts_for" in msg:
            symbol = msg["contracts_for"]
            if symbol not in self.offers:
                await self._send(
                    ws,
                    {
                        **base,
                        "msg_type": "contracts_for",
                        "error": {"code": "InvalidSymbol", "message": "Unknown symbol."},
                    },
                )
            else:
                await self._send(
                    ws,
                    {
                        **base,
                        "msg_type": "contracts_for",
                        "contracts_for": {"available": self.offers[symbol], "hit_count": 1},
                    },
                )
        elif "proposal" in msg:
            symbol = msg["underlying_symbol"]
            if symbol in self.proposal_errors:
                await self._send(
                    ws, {**base, "msg_type": "proposal", "error": self.proposal_errors[symbol]}
                )
                return
            stake = Decimal(str(msg["amount"]))
            total = stake * (100 + self.payouts.get(symbol, 85)) / 100
            await self._send(
                ws,
                {
                    **base,
                    "msg_type": "proposal",
                    "proposal": {
                        "id": uuid.uuid4().hex,
                        "ask_price": float(stake),
                        "payout": float(total),
                        "date_start": 0,
                        "longcode": "",
                        "spot": 1.0,
                        "spot_time": 0,
                    },
                },
            )
        elif "buy" in msg:
            await self._buy(ws, kind, msg, base)
        elif "proposal_open_contract" in msg:
            contract = self.contracts.get(int(msg["contract_id"]))
            if contract is None:
                await self._send(
                    ws,
                    {
                        **base,
                        "msg_type": "proposal_open_contract",
                        "error": {"code": "InvalidContractId", "message": "No such contract."},
                    },
                )
                return
            sub = uuid.uuid4().hex
            self._watchers.setdefault(contract.contract_id, []).append((ws, req_id, sub))
            await self._send(
                ws,
                {
                    **base,
                    "msg_type": "proposal_open_contract",
                    "proposal_open_contract": contract.state(),
                    "subscription": {"id": sub},
                },
            )
        elif "ticks" in msg:
            sub = uuid.uuid4().hex
            self._tick_streams.setdefault(msg["ticks"], []).append((ws, req_id, sub))
            await self._send(ws, {**base, "msg_type": "tick", "subscription": {"id": sub}})
        elif "ping" in msg:
            await self._send(ws, {**base, "msg_type": "ping", "ping": "pong"})
        elif "forget" in msg:
            await self._send(ws, {**base, "msg_type": "forget", "forget": 1})

    async def _buy(
        self, ws: ServerConnection, kind: AccountType, msg: dict[str, Any], base: dict[str, Any]
    ) -> None:
        if self.buy_errors:
            await self._send(ws, {**base, "msg_type": "buy", "error": self.buy_errors.pop(0)})
            return
        params = msg["parameters"]
        contract = Contract(
            contract_id=next(self._ids),
            symbol=params["underlying_symbol"],
            contract_type=params["contract_type"],
            stake=Decimal(str(params["amount"])),
        )
        # Fixed in order of purchase, whichever settles first.
        contract.planned = self._next_profit(contract)
        self.contracts[contract.contract_id] = contract
        self.balances[kind] -= contract.stake
        reply = {
            **base,
            "msg_type": "buy",
            "buy": {
                "contract_id": contract.contract_id,
                "buy_price": float(contract.stake),
                "payout": float(contract.stake * 2),
                "balance_after": float(self.balances[kind]),
                "longcode": "",
                "shortcode": "",
                "purchase_time": 0,
                "start_time": 0,
                "transaction_id": contract.contract_id * 10,
            },
        }
        await self._push_balance(kind)
        if self.settle_after_s is not None:
            asyncio.get_running_loop().call_later(
                self.settle_after_s,
                lambda: asyncio.ensure_future(self.settle(contract.contract_id)),
            )
        if not self.answer_orders:
            return
        if self.reverse_orders:
            self._held.append((ws, reply))
            if len(self._held) >= self.reverse_orders:
                held, self._held = self._held, []
                for client, answer in reversed(held):
                    await self._send(client, answer)
            return
        await self._send(ws, reply)

    def _next_profit(self, contract: Contract) -> Decimal:
        if self.profits:
            return self.profits.pop(0)
        return (contract.stake * self.payouts.get(contract.symbol, 85) / 100).quantize(
            Decimal("0.01")
        )

    async def _after_settle(self, contract: Contract) -> None:
        if contract.profit is not None and contract.profit > 0:
            self.balances[AccountType.DEMO] += contract.stake + contract.profit
        await self._push_contract(contract, keep_watching=False)
        await self._push_balance(AccountType.DEMO)

    async def _push_contract(self, contract: Contract, *, keep_watching: bool) -> None:
        watchers = self._watchers.get(contract.contract_id, [])
        if not keep_watching:
            self._watchers.pop(contract.contract_id, None)
        for ws, req_id, sub in list(watchers):
            update: dict[str, Any] = {
                "msg_type": "proposal_open_contract",
                "proposal_open_contract": contract.state(),
                "subscription": {"id": sub},
            }
            if self.stream_req_id:
                update["req_id"] = req_id
            await self._send(ws, update)

    def _balance(self, kind: AccountType, sub: str) -> dict[str, Any]:
        return {
            "balance": float(self.balances[kind]),
            "currency": self.currency,
            "loginid": self.loginids[kind],
            "id": sub,
        }

    async def _push_balance(self, kind: AccountType) -> None:
        for ws, req_id, sub, stream_kind in list(self._balance_streams):
            if stream_kind is kind:
                update: dict[str, Any] = {
                    "msg_type": "balance",
                    "balance": self._balance(kind, sub),
                    "subscription": {"id": sub},
                }
                if self.stream_req_id:
                    update["req_id"] = req_id
                await self._send(ws, update)
