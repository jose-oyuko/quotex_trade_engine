"""Guards that protect an API which can place trades (the login itself is `app/auth`).

Binding to loopback keeps other computers out, but not the owner's *browser*: any web page the
owner opens can make the browser send requests to `127.0.0.1`. So, on top of the bind rule
(Phase 0):

- **Host check** (loopback bind only): only requests addressed to localhost / 127.0.0.1 / ::1 are
  served. This defeats DNS rebinding, where a hostile name is pointed at 127.0.0.1.
- **Origin check**: a request that can change something (anything but GET/HEAD/OPTIONS, and every
  WebSocket) is refused if the browser says it comes from another site. Programs such as curl send
  no `Origin` and are fine; the dashboard sends its own origin.
- **Body size limit** and a **rate limit on commands**, so nothing here can be flooded.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import urlsplit

from app.api.errors import error_response

type Scope = MutableMapping[str, Any]
type Message = MutableMapping[str, Any]
type Receive = Callable[[], Awaitable[Message]]
type Send = Callable[[Message], Awaitable[None]]
type ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
DEFAULT_MAX_BODY = 64 * 1024


class TokenBucket:
    """`burst` commands at once, then `rate_per_s` per second."""

    def __init__(
        self, rate_per_s: float, burst: int, now: Callable[[], float] = time.monotonic
    ) -> None:
        self._rate = rate_per_s
        self._burst = float(burst)
        self._now = now
        self._tokens = float(burst)
        self._at = now()

    def take(self) -> bool:
        now = self._now()
        self._tokens = min(self._burst, self._tokens + (now - self._at) * self._rate)
        self._at = now
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False


def _host_name(host_header: str) -> str:
    """`127.0.0.1:8000` -> `127.0.0.1`; `[::1]:8000` -> `[::1]`."""
    if host_header.startswith("["):
        return host_header.split("]", 1)[0] + "]"
    return host_header.rsplit(":", 1)[0] if host_header.count(":") == 1 else host_header


class SecurityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        check_host: bool,
        extra_origins: frozenset[str] = frozenset(),
        max_body: int = DEFAULT_MAX_BODY,
        bucket: TokenBucket | None = None,
    ) -> None:
        self.app = app
        self._check_host = check_host
        self._extra_origins = extra_origins
        self._max_body = max_body
        self._bucket = bucket

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        origin = headers.get("origin")
        unsafe = kind == "websocket" or scope["method"] not in SAFE_METHODS

        if self._check_host and _host_name(host).lower() not in LOOPBACK_HOSTS:
            await self._refuse(
                scope, send, 403, "host_not_allowed", "This host name is not served."
            )
        elif unsafe and origin is not None and not self._origin_allowed(origin, host):
            await self._refuse(
                scope, send, 403, "origin_not_allowed", "Requests from other sites are refused."
            )
        elif kind == "http" and unsafe and self._bucket is not None and not self._bucket.take():
            await self._refuse(
                scope, send, 429, "too_many_requests", "Slow down: too many commands."
            )
        elif kind == "http" and int(headers.get("content-length") or 0) > self._max_body:
            await self._refuse(
                scope, send, 413, "payload_too_large", "The request body is too large."
            )
        elif kind == "http":
            await self._limited(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    def _origin_allowed(self, origin: str, host: str) -> bool:
        return origin in self._extra_origins or urlsplit(origin).netloc.lower() == host.lower()

    async def _limited(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request on, counting body bytes that arrive without a Content-Length. Past the
        limit the app is handed an empty end of body, and whatever it then answers is replaced by a
        413 (FastAPI would turn a read error into a 400, which would hide the real reason)."""
        received = 0
        too_large = False
        replaced = False

        async def counting_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_body:
                    too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def replacing_send(message: Message) -> None:
            nonlocal replaced
            if too_large:
                if not replaced:
                    replaced = True
                    await self._refuse(
                        scope, send, 413, "payload_too_large", "The request body is too large."
                    )
                return
            await send(message)

        await self.app(scope, counting_receive, replacing_send)

    @staticmethod
    async def _refuse(scope: Scope, send: Send, status: int, code: str, message: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})  # policy violation -> HTTP 403
            return
        response = error_response(status, code, message)
        await response(scope, _no_receive, send)


async def _no_receive() -> Message:
    return {"type": "http.disconnect"}
