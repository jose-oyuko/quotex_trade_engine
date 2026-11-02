"""FastAPI application and lifespan. Later phases start the engine from the lifespan."""

from __future__ import annotations

from collections.abc import AsyncIterator
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
from app.events.bus import EventBus

VERSION = "0.1.0"
log = structlog.get_logger()


class DatabaseNotMigratedError(RuntimeError):
    """The database file is missing tables or is behind the code."""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass their own settings."""
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

        yield

        # Shutdown runs in reverse order of startup: the writer drains its queue first, so events
        # published just before shutdown still reach the database.
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

    if settings.environment == "development":
        app.add_middleware(
            CORSMiddleware, allow_origins=[settings.cors_origin], allow_methods=["*"]
        )

    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
