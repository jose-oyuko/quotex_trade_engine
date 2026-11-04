"""Watch the live feed (`/ws`) of a running backend, one line per message.

    npm run api:watch -- --username owner
    npm run api:watch -- --username owner --url ws://127.0.0.1:8000/ws

It is what a dashboard receives: a snapshot first, then numbered events and heartbeats. The feed
needs a login like the dashboard does: give your username and it asks for the password (or reads
QTE_PASSWORD). Press Ctrl+C to stop. It only listens (it sends nothing), so it cannot change
anything.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

DEFAULT_URL = "ws://127.0.0.1:8000/ws"


def _count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def describe(message: dict[str, object]) -> str:
    """A short human line for a frame."""
    kind, seq = message.get("type"), message.get("seq")
    data = message.get("data")
    detail = ""
    if kind == "snapshot" and isinstance(data, dict):
        connections = data.get("connections")
        names = sorted(connections) if isinstance(connections, dict) else []
        detail = (
            f"reason={message.get('reason')} account={data.get('account_type')} "
            f"open_chains={_count(data.get('open_chains'))} "
            f"open_trades={_count(data.get('open_trades'))} connections={names}"
        )
    elif isinstance(data, dict):
        keys = ("asset", "status", "step", "stake", "profit", "kind", "message", "component")
        detail = " ".join(f"{k}={data[k]}" for k in keys if data.get(k) is not None)
    return f"#{seq} {kind} {detail}".rstrip()


async def login_cookie(ws_url: str, username: str, password: str) -> str:
    """Log in like the dashboard does and return the cookie header for the socket."""
    base = ws_url.replace("ws://", "http://", 1).replace("wss://", "https://", 1)
    base = base.rsplit("/ws", 1)[0]
    async with httpx.AsyncClient(base_url=base) as client:
        response = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        response.raise_for_status()
        return "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)


async def watch(url: str, cookie: str | None = None) -> None:
    headers = {"Cookie": cookie} if cookie else {}
    async with connect(url, additional_headers=headers) as socket:
        sys.stdout.write(f"connected to {url}\n")
        async for frame in socket:
            sys.stdout.write(describe(json.loads(frame)) + "\n")
            sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--username", help="the owner's username (the feed needs a login)")
    args = parser.parse_args()
    try:
        cookie = None
        if args.username:
            password = os.environ.get("QTE_PASSWORD") or getpass.getpass("Password: ")
            cookie = asyncio.run(login_cookie(args.url, args.username, password))
        asyncio.run(watch(args.url, cookie))
    except KeyboardInterrupt:
        return 0
    except (OSError, WebSocketException, httpx.HTTPError) as exc:
        sys.stderr.write(
            f"cannot watch {args.url}: {exc}\n"
            "Is the backend running (npm run backend), and did you give --username?\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
