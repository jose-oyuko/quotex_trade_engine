"""Health endpoint. Grows with each phase (Telegram, Quotex, ...)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from app.api.schemas.status import ConnectionOut, EngineStatus

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
    engine: EngineStatus
    telegram: ConnectionOut | None = None  # null until the engine has reported
    quotex: ConnectionOut | None = None
    last_event_at: datetime | None = None
    ws_clients: int = 0


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Liveness check. Contains no secrets."""
    state = request.app.state
    writer = state.writer
    live, hub = state.live, state.hub
    connections = live.connections if live is not None else {}

    def component(name: str) -> ConnectionOut | None:
        status = connections.get(name)
        return (
            None
            if status is None
            else ConnectionOut(connected=status.connected, detail=status.detail, since=status.since)
        )

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
        engine=EngineStatus(
            enabled=state.settings.engine_enabled, running=state.trading is not None
        ),
        telegram=component("telegram"),
        quotex=component("quotex"),
        last_event_at=live.last_event_at if live is not None else None,
        ws_clients=hub.clients if hub is not None else 0,
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
