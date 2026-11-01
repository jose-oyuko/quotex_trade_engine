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

VERSION = "0.1.0"
log = structlog.get_logger()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass their own settings."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, json_output=settings.environment == "production")
        log.info("startup", environment=settings.environment, host=settings.host)
        yield
        # Shutdown runs in reverse order of startup; later phases add the engine and DB writer.
        await app.state.tasks.shutdown()
        log.info("shutdown")

    app = FastAPI(title="Quotex Trade Engine", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.tasks = TaskSupervisor()

    if settings.environment == "development":
        app.add_middleware(
            CORSMiddleware, allow_origins=[settings.cors_origin], allow_methods=["*"]
        )

    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
