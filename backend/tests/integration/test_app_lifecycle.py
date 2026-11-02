import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from alembic import command

from app.core.config import Settings
from app.db.engine import create_engine, create_session_factory
from app.db.migrations import alembic_config
from app.db.repositories import GroupRepository, SignalRepository
from app.domain.enums import SignalStatus
from app.events.types import SignalReceived
from app.main import DatabaseNotMigratedError, create_app
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
