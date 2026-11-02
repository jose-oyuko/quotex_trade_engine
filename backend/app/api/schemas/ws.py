"""The WebSocket protocol (`/ws`). These models are part of the OpenAPI document (see
`app/api/openapi.py`), so the frontend's types are generated from them like everything else.

Server -> client, as JSON text frames. Every message has `type`, `seq` and `at`:

- `snapshot` first, and again whenever the client falls behind or asks (`resync`). It replaces the
  client's whole picture.
- `event` messages, named by their `type` (`trade.settled`...), each carrying the full record, with
  `seq` going up by exactly 1. A jump means the client missed something: send `resync`.
- `heartbeat` when nothing else was sent for a while; its `seq` is the latest event number, so a
  client that is behind notices even on a quiet system.

Client -> server: `{"type": "resync"}` asks for a fresh snapshot.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.api.schemas.records import BalanceOut, ChainOut, RiskEventOut, SignalOut, TradeOut
from app.api.schemas.risk import ControlsOut
from app.api.schemas.status import SnapshotOut
from app.domain.enums import AccountType


class ConnectionEventOut(BaseModel):
    component: str
    connected: bool
    detail: str | None


class AccountEventOut(BaseModel):
    account_type: AccountType


class _Message(BaseModel):
    seq: int = Field(ge=0, description="Number of the latest event this message includes.")
    at: datetime


class SnapshotMessage(_Message):
    type: Literal["snapshot"] = "snapshot"
    reason: Literal["connect", "resync", "slow_consumer"]
    data: SnapshotOut


class HeartbeatMessage(_Message):
    type: Literal["heartbeat"] = "heartbeat"


class SignalReceivedMessage(_Message):
    type: Literal["signal.received"] = "signal.received"
    data: SignalOut


class ChainStartedMessage(_Message):
    type: Literal["chain.started"] = "chain.started"
    data: ChainOut


class ChainAdvancedMessage(_Message):
    type: Literal["chain.advanced"] = "chain.advanced"
    data: ChainOut


class ChainEndedMessage(_Message):
    type: Literal["chain.ended"] = "chain.ended"
    data: ChainOut


class TradeOpenedMessage(_Message):
    type: Literal["trade.opened"] = "trade.opened"
    data: TradeOut


class TradeSettledMessage(_Message):
    type: Literal["trade.settled"] = "trade.settled"
    data: TradeOut


class RiskTrippedMessage(_Message):
    type: Literal["risk.tripped"] = "risk.tripped"
    data: RiskEventOut


class BalanceUpdatedMessage(_Message):
    type: Literal["balance.updated"] = "balance.updated"
    data: BalanceOut


class ConnectionChangedMessage(_Message):
    type: Literal["connection.changed"] = "connection.changed"
    data: ConnectionEventOut


class AccountChangedMessage(_Message):
    type: Literal["account.changed"] = "account.changed"
    data: AccountEventOut


class ControlsChangedMessage(_Message):
    type: Literal["controls.changed"] = "controls.changed"
    data: ControlsOut


type ServerMessage = Annotated[
    SnapshotMessage
    | HeartbeatMessage
    | SignalReceivedMessage
    | ChainStartedMessage
    | ChainAdvancedMessage
    | ChainEndedMessage
    | TradeOpenedMessage
    | TradeSettledMessage
    | RiskTrippedMessage
    | BalanceUpdatedMessage
    | ConnectionChangedMessage
    | AccountChangedMessage
    | ControlsChangedMessage,
    Field(discriminator="type"),
]

SERVER_MESSAGE_MODELS: tuple[type[BaseModel], ...] = (
    SnapshotMessage,
    HeartbeatMessage,
    SignalReceivedMessage,
    ChainStartedMessage,
    ChainAdvancedMessage,
    ChainEndedMessage,
    TradeOpenedMessage,
    TradeSettledMessage,
    RiskTrippedMessage,
    BalanceUpdatedMessage,
    ConnectionChangedMessage,
    AccountChangedMessage,
    ControlsChangedMessage,
)


class ResyncRequest(BaseModel):
    """The only message a client may send."""

    type: Literal["resync"]
