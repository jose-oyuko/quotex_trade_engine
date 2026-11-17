"""One WebSocket to Deriv (decision D-77).

Every request carries its own `req_id` and its reply is matched by it, so any number of requests may
be in flight at once: two orders sent together each get their own confirmation, whichever comes back
first. Updates of a subscription (`balance`, `proposal_open_contract`) are routed by `req_id` and by
`subscription.id`. Nothing here waits on anything but the socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable, Coroutine
from itertools import count
from typing import Any

import structlog
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from app.brokers.errors import BrokerConnectionError, NotConnectedError

log = structlog.get_logger()

type Message = dict[str, Any]
type OnUpdate = Callable[[Message], None]
type Spawn = Callable[[Coroutine[Any, Any, Any], str], asyncio.Task[Any]]


class ConnectionLostError(BrokerConnectionError):
    """The socket closed while a reply was awaited: the request may have reached Deriv."""


class DerivConnection:
    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws
        self._ids = count(1)
        self._waiting: dict[int, asyncio.Future[Message]] = {}
        self._streams: dict[int, OnUpdate] = {}
        self._by_subscription: dict[str, OnUpdate] = {}
        self._closed = asyncio.Event()
        self._reader: asyncio.Task[None] | None = None

    @classmethod
    async def open(cls, url: str, *, spawn: Spawn, timeout_s: float) -> DerivConnection:
        """Open the socket and start reading. The link is used once (it holds a one-time code)."""
        ws = await connect(url, open_timeout=timeout_s, max_size=2**22)
        connection = cls(ws)
        connection._reader = spawn(connection._read(), "deriv_reader")
        return connection

    @property
    def is_open(self) -> bool:
        return not self._closed.is_set()

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def request(
        self, payload: Message, *, timeout_s: float, on_update: OnUpdate | None = None
    ) -> Message:
        """Send `payload` and return the first reply to it. With `on_update`, the later messages
        of the subscription go there until `forget`. Raises `NotConnectedError` if nothing could be
        sent, `ConnectionLostError` if the socket closed after sending, `TimeoutError` if no reply
        came in time (the request may then have reached Deriv)."""
        if self._closed.is_set():
            raise NotConnectedError("the connection to Deriv is closed; nothing was sent")
        req_id = next(self._ids)
        reply: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
        self._waiting[req_id] = reply
        if on_update is not None:
            self._streams[req_id] = on_update
        try:
            try:
                await self._ws.send(json.dumps({**payload, "req_id": req_id}))
            except ConnectionClosed as exc:
                raise NotConnectedError("the connection to Deriv closed; nothing was sent") from exc
            async with asyncio.timeout(timeout_s):
                message = await reply
        except BaseException:
            self._waiting.pop(req_id, None)
            self._streams.pop(req_id, None)
            raise
        subscription = _subscription_id(message)
        if on_update is not None:
            if "error" in message:
                self._streams.pop(req_id, None)
            elif subscription is not None:
                self._by_subscription[subscription] = on_update
        return message

    async def forget(self, first_reply: Message, *, timeout_s: float = 5.0) -> None:
        """Stop a subscription started by `request(..., on_update=...)`. Best effort: the updates
        stop reaching their handler at once, whatever Deriv answers."""
        req_id = first_reply.get("req_id")
        if isinstance(req_id, int):
            self._streams.pop(req_id, None)
        subscription = _subscription_id(first_reply)
        if subscription is None:
            return
        self._by_subscription.pop(subscription, None)
        if self.is_open:
            with contextlib.suppress(BrokerConnectionError, TimeoutError):
                await self.request({"forget": subscription}, timeout_s=timeout_s)

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._ws.close()
        self._lost()
        reader = self._reader
        if reader is not None and reader is not asyncio.current_task():
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.shield(reader), timeout=2.0)

    # ---- reading -----------------------------------------------------------------------------

    async def _read(self) -> None:
        try:
            async for frame in self._ws:
                try:
                    message = json.loads(frame)
                except ValueError:
                    log.warning("deriv_unreadable_message", size=len(frame))
                    continue
                if isinstance(message, dict):
                    self._route(message)
        except ConnectionClosed:
            pass
        finally:
            self._lost()

    def _route(self, message: Message) -> None:
        req_id = message.get("req_id")
        if isinstance(req_id, int):
            waiting = self._waiting.pop(req_id, None)
            if waiting is not None:
                if not waiting.done():
                    waiting.set_result(message)
                return
            handler = self._streams.get(req_id)
            if handler is not None:
                self._deliver(handler, message)
                return
        subscription = _subscription_id(message)
        if subscription is not None:
            handler = self._by_subscription.get(subscription)
            if handler is not None:
                self._deliver(handler, message)

    @staticmethod
    def _deliver(handler: OnUpdate, message: Message) -> None:
        try:
            handler(message)
        except Exception:
            log.error(
                "deriv_update_handler_failed", msg_type=message.get("msg_type"), exc_info=True
            )

    def _lost(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        waiting, self._waiting = self._waiting, {}
        for future in waiting.values():
            if not future.done():
                future.set_exception(ConnectionLostError("the connection to Deriv was lost"))
        self._streams.clear()
        self._by_subscription.clear()


def _subscription_id(message: Message) -> str | None:
    subscription = message.get("subscription")
    if isinstance(subscription, dict) and isinstance(subscription.get("id"), str):
        return str(subscription["id"])
    return None
