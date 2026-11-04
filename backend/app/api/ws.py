"""The `/ws` endpoint. The protocol is described in `app/api/schemas/ws.py`; the fan-out logic lives
in `app/api/hub.py`. This module only moves frames between one socket and one hub client."""

from __future__ import annotations

import asyncio
import contextlib

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.hub import ClientClosedError, Hub, HubClient
from app.api.schemas.ws import ResyncRequest
from app.auth.service import SESSION_COOKIE, AuthService

router = APIRouter()
log = structlog.get_logger()

SEND_TIMEOUT_S = 10.0  # a client that cannot take one frame in this long is gone
MAX_CLIENT_MESSAGE = 1024  # the only thing a client may say is {"type": "resync"}
CLOSE_TOO_BIG = 1009
CLOSE_POLICY = 1008
CLOSE_SLOW = 1013  # "try again later"


@router.websocket("/ws")
async def live_socket(websocket: WebSocket) -> None:
    hub: Hub = websocket.app.state.hub
    auth: AuthService = websocket.app.state.auth
    if await auth.authenticate(websocket.cookies.get(SESSION_COOKIE)) is None:
        await websocket.close(code=CLOSE_POLICY)  # before accept: the handshake is answered 403
        return
    await websocket.accept()
    client = hub.register()
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(_send_loop(websocket, hub, client))
            group.create_task(_receive_loop(websocket, client))
    except* (WebSocketDisconnect, ClientClosedError):
        pass  # the normal ways for a connection to end
    except* TimeoutError:
        hub.stats.slow_disconnects += 1
        log.warning("ws_client_too_slow")
        await _close(websocket, CLOSE_SLOW)
    except* RuntimeError:
        pass  # the socket was already closed under us
    finally:
        hub.unregister(client)


async def _send_loop(websocket: WebSocket, hub: Hub, client: HubClient) -> None:
    while True:
        text = await client.next_text(hub.heartbeat_s)
        async with asyncio.timeout(SEND_TIMEOUT_S):
            await websocket.send_text(text)


async def _receive_loop(websocket: WebSocket, client: HubClient) -> None:
    while True:
        text = await websocket.receive_text()
        if len(text) > MAX_CLIENT_MESSAGE:
            await _close(websocket, CLOSE_TOO_BIG)
            raise WebSocketDisconnect(CLOSE_TOO_BIG)
        try:
            ResyncRequest.model_validate_json(text)
        except ValidationError:
            continue  # not something we understand: ignore it, never echo it back
        client.request_snapshot("resync")


async def _close(websocket: WebSocket, code: int) -> None:
    with contextlib.suppress(RuntimeError):  # already closed
        await websocket.close(code=code)
