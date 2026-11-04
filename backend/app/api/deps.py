"""FastAPI dependencies: how a request handler gets at the application's parts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.snapshot import SnapshotBuilder
from app.auth.service import SESSION_COOKIE, AuthService, UserInfo
from app.core.config import Settings
from app.engine.controller import EngineController
from app.engine.engine import Engine
from app.services.app_config import ConfigService
from app.services.groups import GroupService
from app.services.live import LiveState
from app.services.quotex_login import QuotexLoginService
from app.services.risk_settings import RiskSettingsService
from app.services.telegram_login import TelegramLoginService
from app.vault.store import SecretStore


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One short read session per request."""
    factory = request.app.state.session_factory
    if factory is None:
        raise ApiError(503, "unavailable", "The application is still starting.")
    async with factory() as session:
        yield session


def get_engine(request: Request) -> Engine | None:
    """The trading engine, or None when it is not running."""
    engine: Engine | None = request.app.state.trading
    return engine


def require_engine(request: Request) -> Engine:
    engine = get_engine(request)
    if engine is None:
        raise ApiError(
            503,
            "engine_not_running",
            "The trading engine is not running. Start it on the Settings page.",
        )
    return engine


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_live(request: Request) -> LiveState:
    live: LiveState = request.app.state.live
    return live


def get_groups(request: Request) -> GroupService:
    groups: GroupService = request.app.state.groups
    return groups


def get_risk_settings(request: Request) -> RiskSettingsService:
    service: RiskSettingsService = request.app.state.risk_settings
    return service


def get_snapshots(request: Request) -> SnapshotBuilder:
    snapshots: SnapshotBuilder = request.app.state.snapshots
    return snapshots


def get_auth(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


async def current_user(request: Request) -> UserInfo:
    """The logged-in user, or a 401. Every route except `/health` and `/auth/*` depends on this
    (it is attached where the routers are included, in `app/main.py`)."""
    auth: AuthService | None = request.app.state.auth
    if auth is None:
        raise ApiError(503, "unavailable", "The application is still starting.")
    user = await auth.authenticate(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise ApiError(401, "not_authenticated", "Log in to continue.")
    return user


def get_telegram_login(request: Request) -> TelegramLoginService:
    service: TelegramLoginService = request.app.state.telegram_login
    return service


def get_quotex_login(request: Request) -> QuotexLoginService:
    service: QuotexLoginService = request.app.state.quotex_login
    return service


def get_controller(request: Request) -> EngineController:
    controller: EngineController = request.app.state.controller
    return controller


def get_config(request: Request) -> ConfigService:
    config: ConfigService = request.app.state.config
    return config


def get_vault(request: Request) -> SecretStore:
    vault: SecretStore = request.app.state.vault
    return vault


SessionDep = Annotated[AsyncSession, Depends(get_session)]
EngineDep = Annotated[Engine | None, Depends(get_engine)]
RunningEngineDep = Annotated[Engine, Depends(require_engine)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
LiveDep = Annotated[LiveState, Depends(get_live)]
GroupsDep = Annotated[GroupService, Depends(get_groups)]
RiskSettingsDep = Annotated[RiskSettingsService, Depends(get_risk_settings)]
SnapshotsDep = Annotated[SnapshotBuilder, Depends(get_snapshots)]
AuthDep = Annotated[AuthService, Depends(get_auth)]
CurrentUserDep = Annotated[UserInfo, Depends(current_user)]
QuotexLoginDep = Annotated[QuotexLoginService, Depends(get_quotex_login)]
TelegramLoginDep = Annotated[TelegramLoginService, Depends(get_telegram_login)]
ControllerDep = Annotated[EngineController, Depends(get_controller)]
ConfigDep = Annotated[ConfigService, Depends(get_config)]
VaultDep = Annotated[SecretStore, Depends(get_vault)]
