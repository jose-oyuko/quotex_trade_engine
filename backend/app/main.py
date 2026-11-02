"""FastAPI application and lifespan. Later phases start the engine from the lifespan."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.tasks import TaskSupervisor
from app.db.engine import create_engine, create_session_factory
from app.db.migrations import schema_is_current
from app.db.recovery import load_recovery_state
from app.db.writer import DBWriter
from app.engine.engine import Engine
from app.engine.factory import build_engine
from app.events.bus import EventBus

VERSION = "0.1.0"
log = structlog.get_logger()


type EngineBuilder = Callable[[Settings, EventBus, TaskSupervisor], Engine]


class DatabaseNotMigratedError(RuntimeError):
    """The database file is missing tables or is behind the code."""


def create_app(
    settings: Settings | None = None, *, engine_builder: EngineBuilder = build_engine
) -> FastAPI:
    """Build the application. Tests pass their own settings (and a fake-backed engine builder)."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, json_output=settings.environment == "production")
        log.info("startup", environment=settings.environment, host=settings.host)

        settings.data_dir.mkdir(parents=True, exist_ok=True)
        engine = create_engine(settings.database_url)
        if not await schema_is_current(engine):
            await engine.dispose()
            raise DatabaseNotMigratedError(
                "The database is missing or out of date. Run `npm run db:upgrade` "
                "(or `alembic upgrade head` in backend/) and start again."
            )
        session_factory = create_session_factory(engine)
        writer = DBWriter(app.state.bus, session_factory, app.state.tasks)
        writer.start()
        app.state.engine = engine
        app.state.writer = writer

        recovery = await load_recovery_state(session_factory)
        app.state.recovery = recovery
        log.info(
            "recovery_loaded",
            groups=len(recovery.groups),
            open_chains=len(recovery.open_chains),
            unsettled_trades=len(recovery.unsettled_trades),
        )

        if settings.engine_enabled:
            try:
                trading = engine_builder(settings, app.state.bus, app.state.tasks)
                summary = await trading.start(recovery)
            except Exception:
                # e.g. a missing login: leave nothing half-started behind, then say what is wrong
                await writer.stop()
                await app.state.tasks.shutdown()
                await engine.dispose()
                raise
            app.state.trading = trading
            log.info(
                "engine_started",
                chains_marked_unknown=summary.chains_marked_unknown,
                trades_marked_unknown=summary.trades_marked_unknown,
            )
        else:
            log.info("engine_disabled", hint="set ENGINE_ENABLED=true in backend/.env to start it")

        yield

        # Shutdown runs in reverse order of startup: the engine stops first (it publishes the last
        # events), then the writer drains its queue, so those events still reach the database.
        if app.state.trading is not None:
            await app.state.trading.stop()
        await writer.stop()
        await app.state.tasks.shutdown()
        await engine.dispose()
        log.info("shutdown")

    app = FastAPI(title="Quotex Trade Engine", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.tasks = TaskSupervisor()
    app.state.bus = EventBus()
    app.state.engine = None
    app.state.writer = None
    app.state.trading = None

    if settings.environment == "development":
        app.add_middleware(
            CORSMiddleware, allow_origins=[settings.cors_origin], allow_methods=["*"]
        )

    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
