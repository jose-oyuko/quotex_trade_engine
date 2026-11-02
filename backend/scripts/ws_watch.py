"""Watch the live feed (`/ws`) of a running backend, one line per message.

    npm run api:watch
    npm run api:watch -- --url ws://127.0.0.1:8000/ws

It is what a dashboard receives: a snapshot first, then numbered events and heartbeats. Press Ctrl+C
to stop. It only listens (it sends nothing), so it cannot change anything.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

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


async def watch(url: str) -> None:
    async with connect(url) as socket:
        sys.stdout.write(f"connected to {url}\n")
        async for frame in socket:
            sys.stdout.write(describe(json.loads(frame)) + "\n")
            sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()
    try:
        asyncio.run(watch(args.url))
    except KeyboardInterrupt:
        return 0
    except (OSError, WebSocketException) as exc:
        sys.stderr.write(
            f"cannot watch {args.url}: {exc}\nIs the backend running (npm run backend)?\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
