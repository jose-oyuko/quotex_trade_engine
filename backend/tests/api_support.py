"""A running application for the API tests: real FastAPI app and lifespan, real (temporary) SQLite
database, and - when asked for - a real engine built on the fake Telegram source and fake Quotex
adapter. Requests go through `httpx` straight into the ASGI app; WebSocket tests use `serve()`."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import uvicorn
from alembic import command
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import passwords
from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.db.engine import create_engine, create_session_factory
from app.db.migrations import alembic_config
from app.engine.engine import Engine
from app.events.bus import EventBus
from app.main import EngineBuilder, create_app
from app.quotex.base import ConnectionState
from app.quotex.fake import FakeQuotexAdapter
from app.telegram import FakeTelegramSource

BASE_URL = "http://127.0.0.1"
OWNER_NAME = "owner"
OWNER_PASSWORD = "correct horse battery staple"
ASSETS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD")

GROUP_BODY: dict[str, Any] = {
    "telegram_chat_id": -1001,
    "title": "Signals A",
    "enabled": True,
    "settings": {
        "parser": "legacy_v1",
        "asset_suffix_mode": "none",
        "timezone": "UTC-3",
        "strategy": "martingale",
        "base_stake": "1.00",
        "max_steps": 2,
        "multipliers": ["2.0", "2.5"],
        "min_payout_pct": 0,
    },
}


def group_body(**overrides: Any) -> dict[str, Any]:
    """A valid request body to create a group; `settings` overrides are merged into the settings."""
    body = {**GROUP_BODY, "settings": dict(GROUP_BODY["settings"])}
    settings = overrides.pop("settings", {})
    body.update(overrides)
    body["settings"].update(settings)
    return body


@dataclass
class FakeParts:
    """The fakes behind the engine, so a test can emit Telegram messages and settle trades."""

    engine: Engine
    adapter: FakeQuotexAdapter
    source: FakeTelegramSource
    _message_id: int = 0

    def signal(self, chat_id: int, text: str) -> None:
        self._message_id += 1
        assert self.source.emit(chat_id, text, message_id=self._message_id)


@dataclass
class ApiRig:
    app: FastAPI
    client: httpx.AsyncClient
    settings: Settings
    parts: list[FakeParts] = field(default_factory=list)

    @property
    def fakes(self) -> FakeParts:
        return self.parts[0]

    async def log_in(self) -> None:
        """Create the owner account and log the client in (its cookie is kept)."""
        await self.app.state.auth.set_owner(username=OWNER_NAME, password=OWNER_PASSWORD)
        response = await self.client.post(
            "/api/v1/auth/login", json={"username": OWNER_NAME, "password": OWNER_PASSWORD}
        )
        assert response.status_code == 200, response.text

    def ws_headers(self) -> dict[str, str]:
        """The login cookie, for a WebSocket opened outside `client` (which holds it)."""
        cookies = "; ".join(f"{c.name}={c.value}" for c in self.client.cookies.jar)
        return {"Cookie": cookies} if cookies else {}

    async def create_group(self, **overrides: Any) -> dict[str, Any]:
        response = await self.client.post("/api/v1/groups", json=group_body(**overrides))
        assert response.status_code == 201, response.text
        body: dict[str, Any] = response.json()
        return body

    async def eventually(
        self, check: Callable[[], Awaitable[bool]], *, tries: int = 400, delay: float = 0.01
    ) -> None:
        for _ in range(tries):
            if await check():
                return
            await asyncio.sleep(delay)
        raise AssertionError("condition not reached in time")


def settings_for(tmp_path: Path, **overrides: Any) -> Settings:
    """Test settings. The dashboard folder defaults to one that does not exist, so a test never
    depends on whether the developer has run `npm run build`."""
    overrides.setdefault("frontend_dir", tmp_path / "no-built-dashboard")
    overrides.setdefault("log_to_file", False)  # tests do not leave log files behind
    return Settings(_env_file=None, data_dir=tmp_path / "data", **overrides)  # type: ignore[call-arg]


async def migrate(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(command.upgrade, alembic_config(settings.database_url), "head")


def fake_builder(parts: list[FakeParts], *, hold_results: bool = False) -> EngineBuilder:
    def build(settings: Settings, bus: EventBus, tasks: TaskSupervisor) -> Engine:
        clock = SystemClock()
        adapter = FakeQuotexAdapter(
            clock=clock, bus=bus, hold_results=hold_results, allow_real=settings.quotex_allow_real
        )
        for asset in ASSETS:
            adapter.add_asset(asset, payout=80)
        source = FakeTelegramSource(clock)
        engine = Engine(adapter=adapter, source=source, bus=bus, clock=clock, tasks=tasks)
        parts.append(FakeParts(engine, adapter, source))
        return engine

    return build


@asynccontextmanager
async def running_api(
    tmp_path: Path,
    *,
    with_engine: bool = False,
    hold_results: bool = False,
    seed: Callable[[async_sessionmaker[AsyncSession]], Awaitable[None]] | None = None,
    logged_in: bool = True,
    builder: EngineBuilder | None = None,
    login_source: Any = None,
    **settings: Any,
) -> AsyncIterator[ApiRig]:
    """The application inside its lifespan, with an HTTP client for it. `seed` fills the database
    before the application starts (reports need history to report on). The client is logged in as
    the owner unless `logged_in=False`. Password hashing is made cheap here (the real cost is tested
    in test_auth_passwords.py): a test must not spend 100 ms of CPU on every login."""
    with patch.object(passwords, "N", 2**4):
        async with _running_api(
            tmp_path,
            with_engine=with_engine,
            hold_results=hold_results,
            seed=seed,
            logged_in=logged_in,
            builder=builder,
            login_source=login_source,
            settings=settings,
        ) as rig:
            yield rig


@asynccontextmanager
async def _running_api(
    tmp_path: Path,
    *,
    with_engine: bool,
    hold_results: bool,
    seed: Callable[[async_sessionmaker[AsyncSession]], Awaitable[None]] | None,
    logged_in: bool,
    builder: EngineBuilder | None,
    login_source: Any,
    settings: dict[str, Any],
) -> AsyncIterator[ApiRig]:
    config = settings_for(tmp_path, engine_enabled=with_engine, **settings)
    await migrate(config)
    if seed is not None:
        engine = create_engine(config.database_url)
        try:
            await seed(create_session_factory(engine))
        finally:
            await engine.dispose()
    parts: list[FakeParts] = []
    app = create_app(
        config,
        engine_builder=builder or fake_builder(parts, hold_results=hold_results),
        login_source=login_source,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client,
    ):
        rig = ApiRig(app, client, config, parts)
        if logged_in:
            await rig.log_in()
        if with_engine and parts:
            engine = rig.fakes.engine
            assert await engine.listener.wait_until_connected(2)
            await rig.eventually(_connected(engine))
        yield rig


def _connected(engine: Engine) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        return engine.adapter.state is ConnectionState.CONNECTED

    return check


class QuietServer(uvicorn.Server):
    """uvicorn without its signal handlers, so it can run inside a test's event loop."""

    def install_signal_handlers(self) -> None:  # pragma: no cover - uvicorn < 0.29 hook
        return


@asynccontextmanager
async def serve(app: FastAPI) -> AsyncIterator[str]:
    """Run the app on a real socket (port chosen by the OS); yields its `ws://` base address."""
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_config=None, lifespan="off", ws_ping_interval=None
    )
    server = QuietServer(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("the test server did not start")
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
