"""Switching a broker off and on while the engine runs (decision D-81)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ControllerDep, EngineDep
from app.api.schemas.brokers import BrokerOut, BrokersOut, BrokerState, BrokerSwitchIn
from app.brokers.base import ConnectionState
from app.domain.enums import Broker
from app.engine.controller import EngineController
from app.engine.engine import Engine

router = APIRouter(tags=["brokers"])

_STATE: dict[ConnectionState, BrokerState] = {
    ConnectionState.CONNECTED: "connected",
    ConnectionState.CONNECTING: "connecting",
    ConnectionState.RECONNECTING: "reconnecting",
    ConnectionState.DISCONNECTED: "disconnected",
}


def brokers_out(controller: EngineController, engine: Engine | None) -> BrokersOut:
    off = controller.brokers_off
    items: list[BrokerOut] = []
    for broker in Broker:
        state: BrokerState
        detail: str | None = None
        adapter = engine.adapters.get(broker) if engine is not None else None
        if broker in off:
            state = "off"
        elif engine is None:
            state = "engine_stopped"
        elif adapter is None:
            state = "no_login"
        elif (problem := engine.login_problem(broker)) is not None:
            state, detail = "needs_you", problem
        else:
            state = _STATE[adapter.state]
        items.append(
            BrokerOut(broker=broker, enabled=broker not in off, state=state, detail=detail)
        )
    return BrokersOut(items=items)


@router.get("/brokers", response_model=BrokersOut)
async def list_brokers(controller: ControllerDep, engine: EngineDep) -> BrokersOut:
    """Each broker: switched on or off, and where its connection is."""
    return brokers_out(controller, engine)


@router.put("/brokers/{broker}", response_model=BrokersOut)
async def set_broker(
    broker: Broker, body: BrokerSwitchIn, controller: ControllerDep, engine: EngineDep
) -> BrokersOut:
    """Switch a broker off (its connection closes and its login attempts stop) or on (it connects
    at once). Remembered across restarts. Switching off is refused (409 `broker_switch_refused`)
    while it has open trades, running chains or a running session."""
    await controller.set_broker_enabled(broker, body.enabled)
    return brokers_out(controller, engine)
