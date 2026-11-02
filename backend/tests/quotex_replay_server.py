"""A local stand-in for the Quotex websocket, for driving the *real* pyquotex library offline.

What it proves: our wrapper (`PyQuotexClient`) and adapter work with pyquotex's real code paths
(connect, message parsing, the order and result slots, reconnect). What it cannot prove: that real
Quotex sends these frames. They are modelled on how pyquotex 1.1.0 itself parses messages (the
"placeholder" flow: a text frame announcing the event, followed by a data frame); whether the live
service matches is checked by the live diagnostic.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.server import ServerConnection, serve


@dataclass
class ReplayQuotexServer:
    rows: list[list[Any]]
    balance: dict[str, Any] = field(
        default_factory=lambda: {"demoBalance": 10000.5, "liveBalance": 25.0}
    )
    reject_auth: bool = False
    send_ticks: bool = True
    send_order_ack: bool = True
    settle_after_s: float | None = 0.05  # None: never settle
    profits: list[float] = field(default_factory=list)  # next order profits; default +0.85
    received: list[tuple[str, Any]] = field(default_factory=list)
    connections: int = 0

    _server: Any = None
    _next_id: int = 0
    _clients: set[ServerConnection] = field(default_factory=set)

    async def start(self) -> str:
        self._server = await serve(self._handle, "127.0.0.1", 0)
        port = next(iter(self._server.sockets)).getsockname()[1]
        return f"ws://127.0.0.1:{port}/socket.io/?EIO=3&transport=websocket"

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def drop_clients(self) -> None:
        """Close every connection from the server side, like a network drop."""
        for client in list(self._clients):
            await client.close()

    def events(self, name: str) -> list[Any]:
        return [payload for event, payload in self.received if event == name]

    # ---- protocol ----------------------------------------------------------------------------

    async def _handle(self, ws: ServerConnection) -> None:
        self.connections += 1
        self._clients.add(ws)
        tasks: set[asyncio.Task[None]] = set()
        try:
            async for frame in ws:
                text = frame.decode() if isinstance(frame, bytes) else frame
                start = text.find("[")
                if start < 0:
                    continue
                try:
                    message = json.loads(text[start:])
                except ValueError:
                    continue
                event = message[0] if message else ""
                payload = message[1] if len(message) > 1 else None
                self.received.append((event, payload))
                task = asyncio.create_task(self._on_event(ws, event, payload))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        except Exception:  # noqa: S110  (a dropped client is normal in these tests)
            pass
        finally:
            self._clients.discard(ws)
            for task in tasks:
                task.cancel()

    async def _on_event(self, ws: ServerConnection, event: str, payload: Any) -> None:
        with contextlib.suppress(Exception):
            if event == "authorization":
                if self.reject_auth:
                    await ws.send('42["authorization/reject"]')
                    return
                await ws.send('42["s_authorization"]')
                await ws.send(f'42["balance",{json.dumps(self.balance)}]')
            elif event == "instruments/get":
                await ws.send(f'42["instruments/list",{json.dumps(self.rows)}]')
            elif event == "depth/follow" and self.send_ticks:
                tick = json.dumps([[payload, 1_730_000_000.5, 1.0832, 0]])
                await ws.send(f"42{tick}")
            elif event == "orders/open":
                await self._open_order(ws, payload)

    async def _open_order(self, ws: ServerConnection, order: dict[str, Any]) -> None:
        self._next_id += 1
        order_id = f"srv-{self._next_id}"
        if self.send_order_ack:
            await self._placeholder(ws, "orders/opened", {"id": order_id, **order})
        if self.settle_after_s is None:
            return
        await asyncio.sleep(self.settle_after_s)
        profit = self.profits.pop(0) if self.profits else 0.85
        await self._placeholder(
            ws, "orders/closed", {"deals": [{"id": order_id, "profit": profit}]}
        )

    @staticmethod
    async def _placeholder(ws: ServerConnection, event: str, data: dict[str, Any]) -> None:
        """Socket.IO 'binary event': a text frame announcing it, then the data frame."""
        await ws.send(f'451-["{event}",{{"_placeholder":true,"num":0}}]')
        await ws.send(json.dumps(data).encode())


ServerFactory = Callable[[], ReplayQuotexServer]
