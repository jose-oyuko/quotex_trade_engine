"""A switch per broker (decision D-81): `GET /brokers` and `PUT /brokers/{broker}`."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import Broker

BrokerState = Literal[
    "off",  # switched off by the owner
    "needs_you",  # stopped trying: a login only the owner can fix (`detail` says why)
    "connected",
    "connecting",
    "reconnecting",
    "disconnected",
    "no_login",  # the engine runs without this broker: its login is not stored
    "engine_stopped",
]


class BrokerOut(BaseModel):
    broker: Broker
    enabled: bool = Field(description="False: the owner switched it off (remembered).")
    state: BrokerState
    detail: str | None = None


class BrokersOut(BaseModel):
    items: list[BrokerOut]


class BrokerSwitchIn(BaseModel):
    enabled: bool
