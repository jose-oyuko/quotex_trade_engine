"""The picture of the whole system: `GET /status` and the first message of the WebSocket."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.api.schemas.records import BalanceOut, ChainOut, TradeOut
from app.api.schemas.risk import ControlsOut, DayOut
from app.domain.enums import AccountType


class ConnectionOut(BaseModel):
    connected: bool
    detail: str | None
    since: datetime


class EngineStatus(BaseModel):
    enabled: bool  # ENGINE_ENABLED in the settings
    running: bool  # the engine was started with this process


class SnapshotOut(BaseModel):
    version: str
    environment: str
    engine: EngineStatus
    account_type: AccountType
    real_trading_allowed: bool
    connections: dict[str, ConnectionOut]
    balance: BalanceOut | None
    controls: ControlsOut
    day: DayOut | None
    open_chains: list[ChainOut]
    open_trades: list[TradeOut]
    last_event_at: datetime | None
