"""The picture of the whole system: `GET /status` and the first message of the WebSocket."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.records import BalanceOut, ChainOut, TradeOut
from app.api.schemas.risk import ControlsOut, DayOut
from app.domain.enums import AccountType, Broker


class ConnectionOut(BaseModel):
    connected: bool
    detail: str | None
    since: datetime


class EngineStatus(BaseModel):
    enabled: bool  # the owner left it on: it is started again when the application starts
    running: bool
    state: Literal["stopped", "starting", "running", "stopping", "failed"] = "stopped"
    error: str | None = None  # why the last start failed


class SnapshotOut(BaseModel):
    version: str
    environment: str
    engine: EngineStatus
    account_type: AccountType
    real_trading_allowed: bool
    connections: dict[str, ConnectionOut]
    brokers: list[Broker] = Field(
        default_factory=list,
        description="The brokers the running engine has (a login for each); empty when stopped.",
    )
    balance: BalanceOut | None = Field(
        description="The balance in use: Quotex's, or the only broker's. See `balances`."
    )
    balances: list[BalanceOut] = Field(
        default_factory=list,
        description="The balance of the account in use on each connected broker (never added up).",
    )
    controls: ControlsOut
    day: DayOut | None
    open_chains: list[ChainOut]
    open_trades: list[TradeOut]
    last_event_at: datetime | None
