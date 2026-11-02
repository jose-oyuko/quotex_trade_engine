"""Health endpoint. Grows with each phase (Telegram, Quotex, ...)."""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter(tags=["health"])
log = structlog.get_logger()


class WriterHealth(BaseModel):
    queue_depth: int
    written: int
    failed: int
    dropped: int


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    environment: str
    background_tasks: int
    database: Literal["ok", "unavailable"]
    events_published: int
    writer: WriterHealth | None


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Liveness check. Contains no secrets."""
    state = request.app.state
    writer = state.writer
    return HealthResponse(
        status="ok",
        version=request.app.version,
        environment=state.settings.environment,
        background_tasks=state.tasks.running,
        database=await _database_status(state.engine),
        events_published=state.bus.published,
        writer=None
        if writer is None
        else WriterHealth(
            queue_depth=writer.queue_depth,
            written=writer.stats.written,
            failed=writer.stats.failed,
            dropped=writer.dropped,
        ),
    )


async def _database_status(engine: object) -> Literal["ok", "unavailable"]:
    if engine is None:
        return "unavailable"
    try:
        async with engine.connect() as connection:  # type: ignore[attr-defined]
            await connection.execute(text("SELECT 1"))
    except Exception:
        log.warning("health_database_check_failed", exc_info=True)
        return "unavailable"
    return "ok"
