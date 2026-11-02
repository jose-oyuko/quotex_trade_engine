"""Health endpoint: is the application alive, and is anything wrong that the owner must know?

`status` is `ok`, or `degraded` with a plain-language `problems` list: the database is unreachable
or not accepting writes, history was lost to an overflow, or (with the engine running) Quotex or
Telegram is disconnected. The dashboard shows these at the top of every page.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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
    retrying: bool = False  # the database is down and records are being held back


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    problems: list[str] = []
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

    database = await _database_status(state.engine)
    engine_running = state.trading is not None
    problems = _problems(
        database=database,
        writer=writer,
        engine_running=engine_running,
        telegram=connections.get("telegram"),
        quotex=connections.get("quotex"),
    )
    return HealthResponse(
        status="degraded" if problems else "ok",
        problems=problems,
        version=request.app.version,
        environment=state.settings.environment,
        background_tasks=state.tasks.running,
        database=database,
        events_published=state.bus.published,
        writer=None
        if writer is None
        else WriterHealth(
            queue_depth=writer.queue_depth,
            written=writer.stats.written,
            failed=writer.stats.failed,
            dropped=writer.dropped,
            retrying=writer.retrying,
        ),
        engine=EngineStatus(
            enabled=state.settings.engine_enabled, running=state.trading is not None
        ),
        telegram=component("telegram"),
        quotex=component("quotex"),
        last_event_at=live.last_event_at if live is not None else None,
        ws_clients=hub.clients if hub is not None else 0,
    )


def _problems(
    *,
    database: str,
    writer: Any,
    engine_running: bool,
    telegram: Any,
    quotex: Any,
) -> list[str]:
    problems: list[str] = []
    if database != "ok":
        problems.append("The database cannot be reached: nothing is being stored.")
    if writer is not None:
        if writer.retrying:
            problems.append(
                "The database is not accepting writes: new records are held in memory and "
                "retried. Check the disk space and that nothing else has the database open."
            )
        if writer.dropped:
            problems.append(
                f"{writer.dropped} events were dropped because the database could not keep up: "
                "some history is missing."
            )
        if writer.stats.failed:
            problems.append(
                f"{writer.stats.failed} records could not be stored. See the log (data/logs)."
            )
    if engine_running:
        if quotex is None or not quotex.connected:
            problems.append("Quotex is not connected: no trade can be placed until it is.")
        if telegram is None or not telegram.connected:
            problems.append("Telegram is not connected: signals are not being read.")
    return problems


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
