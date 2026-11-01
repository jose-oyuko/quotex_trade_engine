"""Health endpoint. Grows with each phase (Telegram, Quotex, DB, queue depth)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    environment: str
    background_tasks: int


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Liveness check. Contains no secrets."""
    state = request.app.state
    return HealthResponse(
        status="ok",
        version=request.app.version,
        environment=state.settings.environment,
        background_tasks=state.tasks.running,
    )
