"""Start, stop and restart the trading engine from the dashboard (decision D-63)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ControllerDep, SettingsDep, VaultDep
from app.api.schemas.engine import EngineOut, LoginItemOut
from app.engine.logins import login_items

router = APIRouter(prefix="/engine", tags=["engine"])


async def engine_out(
    controller: ControllerDep, settings: SettingsDep, vault: VaultDep
) -> EngineOut:
    items = await login_items(settings, vault)
    return EngineOut(
        state=controller.state.value,
        desired=controller.desired,
        error=controller.error,
        since=controller.since,
        real_trading_allowed=controller.real_allowed,
        logins=[
            LoginItemOut(label=i.label, present=i.present, source=i.source, required=i.required)
            for i in items
        ],
        missing_logins=[i.label for i in items if i.required and not i.present],
    )


@router.get("", response_model=EngineOut)
async def get_engine_state(
    controller: ControllerDep, settings: SettingsDep, vault: VaultDep
) -> EngineOut:
    """Whether the engine is running, why it is not, and which logins it has."""
    return await engine_out(controller, settings, vault)


@router.post("/start", response_model=EngineOut)
async def start_engine(
    controller: ControllerDep, settings: SettingsDep, vault: VaultDep
) -> EngineOut:
    """Start the engine on the DEMO account: it connects to Quotex and Telegram and begins taking
    signals. Does nothing if it is running. 409 `engine_start_failed` says why it could not."""
    await controller.start()
    return await engine_out(controller, settings, vault)


@router.post("/stop", response_model=EngineOut)
async def stop_engine(
    controller: ControllerDep, settings: SettingsDep, vault: VaultDep
) -> EngineOut:
    """Stop the engine. Trades that are open stay open on Quotex and run to their expiry; here they
    are marked `unknown` straight away (the application can no longer follow them)."""
    await controller.stop()
    return await engine_out(controller, settings, vault)


@router.post("/restart", response_model=EngineOut)
async def restart_engine(
    controller: ControllerDep, settings: SettingsDep, vault: VaultDep
) -> EngineOut:
    """Stop and start again, for example after changing a stored login."""
    await controller.restart()
    return await engine_out(controller, settings, vault)
