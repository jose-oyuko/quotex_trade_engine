"""Run the whole application on FAKE Quotex and FAKE Telegram, to try the dashboard without any
account, login or money.

    npm run demo                      # then open http://127.0.0.1:8000  (after `npm run build`)
    npm run demo -- --interval 4 --reset

It starts the real backend (API, WebSocket, engine, database) but the "Quotex" is a simulator that
settles every trade after a few seconds with a random result, and the "Telegram groups" are a small
generator that posts a made-up signal now and then. Everything lives in `backend/data/demo/`, a
separate database; your real data and your credentials are never read (no `.env`) and nothing here
can reach Quotex or Telegram. Press Ctrl+C to stop.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from alembic import command

from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.db.engine import create_engine, create_session_factory
from app.db.migrations import alembic_config
from app.engine.engine import Engine
from app.engine.flags import EngineFlags
from app.events.bus import EventBus
from app.main import create_app
from app.quotex.base import TradeOutcome
from app.quotex.fake import FakeQuotexAdapter
from app.telegram import FakeTelegramSource

DEMO_DIR = Path(__file__).resolve().parents[1] / "data" / "demo"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
ASSETS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD")
EXPIRY_S = 15  # short, so a walkthrough does not wait minutes for a result

CHAT_TALK = ("Good morning team!", "Market is quiet today", "Remember to manage your risk")


@dataclass(frozen=True)
class DemoGroup:
    chat_id: int
    title: str
    strategy: str
    base_stake: str
    multipliers: tuple[str, ...]

    def body(self) -> dict[str, Any]:
        return {
            "telegram_chat_id": self.chat_id,
            "title": self.title,
            "enabled": True,
            "settings": {
                "parser": "legacy_v1",
                "asset_suffix_mode": "none",
                "timezone": "UTC",
                "strategy": self.strategy,
                "base_stake": self.base_stake,
                "max_steps": len(self.multipliers),
                "multipliers": list(self.multipliers),
                "min_payout_pct": 0,
            },
        }


GROUPS = (
    DemoGroup(-1001, "Alpha signals (martingale)", "martingale", "1.00", ("2.0", "2.5", "3.0")),
    DemoGroup(-1002, "Beta signals (flip every loss)", "flip_every_loss", "2.00", ("2.0", "2.0")),
    DemoGroup(-1003, "Gamma signals (no martingale)", "no_martingale", "1.50", ()),
)


class DemoFeed:
    """Posts a made-up message to one of the demo groups, and decides how its trade will end."""

    def __init__(
        self,
        source: FakeTelegramSource,
        adapter: FakeQuotexAdapter,
        *,
        win_rate: float = 0.45,
        rng: random.Random | None = None,
        groups: tuple[DemoGroup, ...] = GROUPS,
    ) -> None:
        self._source = source
        self._adapter = adapter
        self._win_rate = win_rate
        self._rng = rng or random.Random()  # noqa: S311  (a demo, not security)
        self._groups = groups
        self._message_id = 0
        self.sent = 0

    def emit_next(self) -> str:
        """One message into one group. Every fifth is chat, not a signal (the inbox shows both)."""
        self.sent += 1
        group = self._rng.choice(self._groups)
        if self.sent % 5 == 0:
            text = self._rng.choice(CHAT_TALK)
        else:
            asset = self._rng.choice(ASSETS)
            direction = self._rng.choice(("CALL", "PUT"))
            text = f"{asset} {direction} {EXPIRY_S}s"
            outcome = TradeOutcome.WON if self._rng.random() < self._win_rate else TradeOutcome.LOST
            self._adapter.script_results(outcome)  # for the first trade; a follow-up draws its own
        self._message_id += 1
        self._source.emit(group.chat_id, text, message_id=self._message_id)
        return text


@dataclass
class Fakes:
    adapter: FakeQuotexAdapter
    source: FakeTelegramSource
    engine: Engine


def fake_builder(holder: list[Fakes]) -> Any:
    """An engine builder that can only produce the simulators: no real adapter is even imported."""

    def build(settings: Settings, bus: EventBus, tasks: TaskSupervisor) -> Engine:
        clock = SystemClock()
        adapter = FakeQuotexAdapter(clock=clock, bus=bus, result_delay_s=EXPIRY_S)
        for asset in ASSETS:
            adapter.add_asset(asset, payout=85)
        source = FakeTelegramSource(clock)
        engine = Engine(adapter=adapter, source=source, bus=bus, clock=clock, tasks=tasks)
        holder.append(Fakes(adapter, source, engine))
        return engine

    return build


DEMO_USER = "demo"
DEMO_PASSWORD = "demo-password"  # noqa: S105 - the demo database is separate and holds nothing real


async def log_in_demo(app: Any, client: httpx.AsyncClient) -> None:
    """The demo has a login like the real application. Its account is made here, with a known
    password, and the client is logged in with it (the cookie stays in the client)."""
    await app.state.auth.set_owner(username=DEMO_USER, password=DEMO_PASSWORD)
    response = await client.post(
        "/api/v1/auth/login", json={"username": DEMO_USER, "password": DEMO_PASSWORD}
    )
    response.raise_for_status()


async def leave_engine_running(settings: Settings) -> None:
    """The demo's engine starts with the application: the owner's choice, remembered in the
    demo's own database like on the real one (decision D-63)."""
    engine = create_engine(settings.database_url)
    try:
        await EngineFlags(create_session_factory(engine), SystemClock()).set_desired(True)
    finally:
        await engine.dispose()


async def seed_groups(client: httpx.AsyncClient) -> int:
    """Create the demo groups through the real API, if there are none yet."""
    existing = (await client.get("/api/v1/groups")).json()["total"]
    if existing:
        return 0
    for group in GROUPS:
        response = await client.post("/api/v1/groups", json=group.body())
        response.raise_for_status()
    return len(GROUPS)


async def run(port: int, interval: float, win_rate: float, reset: bool) -> int:
    if reset and DEMO_DIR.exists():
        if DEMO_DIR.name != "demo":
            raise RuntimeError("refusing to delete anything but the demo folder")
        shutil.rmtree(DEMO_DIR)
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,  # never read the real credentials
        data_dir=DEMO_DIR,
        port=port,
        frontend_dir=FRONTEND_DIST,
    )
    await asyncio.to_thread(command.upgrade, alembic_config(settings.database_url), "head")
    await leave_engine_running(settings)
    holder: list[Fakes] = []
    app = create_app(settings, engine_builder=fake_builder(holder))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None))
    serving = asyncio.create_task(server.serve())
    while not server.started and not serving.done():  # noqa: ASYNC110
        await asyncio.sleep(0.05)
    if serving.done():
        await serving  # it failed to start (port in use?): show why
        return 1
    sys.stdout.write(
        f"\nDEMO MODE (fake Quotex, fake Telegram, separate database)\n"
        f"Dashboard: http://127.0.0.1:{port}   (run `npm run build` first if it is blank)\n"
        f"Log in with username {DEMO_USER!r} and password {DEMO_PASSWORD!r}.\n"
        f"A made-up signal every {interval:g}s; trades settle after {EXPIRY_S}s. Ctrl+C stops.\n\n"
    )
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        await log_in_demo(app, client)
        created = await seed_groups(client)
    if created:
        sys.stdout.write(f"created {created} demo groups\n")
    fakes = holder[0]
    assert await fakes.engine.listener.wait_until_connected(5)  # noqa: S101
    feed = DemoFeed(fakes.source, fakes.adapter, win_rate=win_rate)
    try:
        while not serving.done():
            await asyncio.sleep(interval)
            sys.stdout.write(f"posted: {feed.emit_next()}\n")
            sys.stdout.flush()
    finally:
        server.should_exit = True
        await serving
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--interval", type=float, default=7.0, help="seconds between signals")
    parser.add_argument("--win-rate", type=float, default=0.45)
    parser.add_argument("--reset", action="store_true", help="start from an empty demo database")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args.port, args.interval, args.win_rate, args.reset))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
