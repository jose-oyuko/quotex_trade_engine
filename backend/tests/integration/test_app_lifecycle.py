import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
from alembic import command

from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.db.engine import create_engine, create_session_factory
from app.db.migrations import alembic_config
from app.db.repositories import GroupRepository, SignalRepository
from app.domain.enums import SignalStatus
from app.engine.engine import Engine
from app.events.bus import EventBus
from app.events.types import SignalReceived
from app.main import DatabaseNotMigratedError, EngineBuilder, create_app
from app.quotex.base import ConnectionState
from app.quotex.errors import QuotexError
from app.quotex.fake import FakeQuotexAdapter
from app.telegram import FakeTelegramSource
from tests.factories import NOW, make_group, make_signal


def settings_for(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data")  # type: ignore[call-arg]


@pytest.fixture
async def migrated_settings(tmp_path: Path) -> AsyncIterator[Settings]:
    settings = settings_for(tmp_path)
    settings.data_dir.mkdir(parents=True)
    await asyncio.to_thread(command.upgrade, alembic_config(settings.database_url), "head")
    yield settings


async def get_health(app) -> dict:  # type: ignore[no-untyped-def, type-arg]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return (await client.get("/api/v1/health")).json()  # type: ignore[no-any-return]


async def test_startup_refuses_a_database_that_was_never_migrated(tmp_path: Path) -> None:
    app = create_app(settings_for(tmp_path))
    with pytest.raises(DatabaseNotMigratedError, match="db:upgrade"):
        async with app.router.lifespan_context(app):
            pass


async def test_health_reports_database_and_writer(migrated_settings: Settings) -> None:
    app = create_app(migrated_settings)
    async with app.router.lifespan_context(app):
        health = await get_health(app)
    assert health["database"] == "ok"
    assert health["writer"] == {"queue_depth": 0, "written": 0, "failed": 0, "dropped": 0}
    assert health["events_published"] == 0


async def test_event_published_while_running_is_in_the_database_after_shutdown(
    migrated_settings: Settings,
) -> None:
    # A group has to exist before signals can refer to it.
    engine = create_engine(migrated_settings.database_url)
    factory = create_session_factory(engine)
    async with factory.begin() as session:
        group = await GroupRepository(session).add(make_group())
    await engine.dispose()
    assert group.id is not None

    signal = make_signal(group.id, status=SignalStatus.PARSED)
    app = create_app(migrated_settings)
    async with app.router.lifespan_context(app):
        app.state.bus.publish(SignalReceived(occurred_at=NOW, signal=signal))
        health = await get_health(app)
        assert health["events_published"] == 1
    # Leaving the lifespan flushed the writer.

    engine = create_engine(migrated_settings.database_url)
    try:
        async with create_session_factory(engine)() as session:
            assert await SignalRepository(session).get(signal.id) == signal
    finally:
        await engine.dispose()


async def test_open_chains_are_loaded_at_startup(migrated_settings: Settings) -> None:
    app = create_app(migrated_settings)
    async with app.router.lifespan_context(app):
        recovery = app.state.recovery
    assert (recovery.groups, recovery.open_chains, recovery.unsettled_trades) == ([], [], [])


# --- the trading engine inside the application ---


def fake_engine_builder(captured: list[Engine]) -> EngineBuilder:
    def build(settings: Settings, bus: EventBus, tasks: TaskSupervisor) -> Engine:
        clock = SystemClock()
        adapter = FakeQuotexAdapter(clock=clock, bus=bus)
        engine = Engine(
            adapter=adapter, source=FakeTelegramSource(clock), bus=bus, clock=clock, tasks=tasks
        )
        captured.append(engine)
        return engine

    return build


async def test_the_engine_does_not_start_unless_it_is_enabled(migrated_settings: Settings) -> None:
    captured: list[Engine] = []
    app = create_app(migrated_settings, engine_builder=fake_engine_builder(captured))
    async with app.router.lifespan_context(app):
        assert app.state.trading is None
    assert captured == []


async def test_an_enabled_engine_starts_with_the_app_and_stops_before_the_writer(
    migrated_settings: Settings,
) -> None:
    captured: list[Engine] = []
    enabled = migrated_settings.model_copy(update={"engine_enabled": True})
    app = create_app(enabled, engine_builder=fake_engine_builder(captured))
    async with app.router.lifespan_context(app):
        [engine] = captured
        assert app.state.trading is engine
        assert await engine.listener.wait_until_connected(2)
        await wait_for(lambda: engine.adapter.state is ConnectionState.CONNECTED)
    assert engine.listener.state.value == "stopped"
    assert engine.adapter.state is ConnectionState.DISCONNECTED


async def test_a_missing_login_stops_start_up_with_a_clear_error(
    migrated_settings: Settings,
) -> None:
    enabled = migrated_settings.model_copy(update={"engine_enabled": True})
    app = create_app(enabled)  # the real builder, no credentials in these settings
    with pytest.raises(QuotexError, match="QUOTEX_EMAIL"):
        async with app.router.lifespan_context(app):
            pass


async def wait_for(condition: Callable[[], bool]) -> None:
    for _ in range(500):
        if condition():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")
