"""Deriv on the dashboard (Phase 21): checking a stored token without trading, and Deriv's list
of assets for the session form.

The check reads Deriv's account list only (no socket, no order), with the logins the engine would
use: the ones stored on the dashboard, else `backend/.env`. The asset list comes from the running
engine's memory, so it is there only while the engine is connected to Deriv.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog

from app.brokers.base import AssetOffer, BrokerAccount, ConnectionState
from app.brokers.errors import BrokerConnectionError, BrokerError, LoginRejectedError
from app.core.config import Settings
from app.core.errors import DomainError
from app.domain.enums import AccountType, Broker
from app.engine.engine import Engine
from app.engine.errors import EngineStartError
from app.engine.logins import resolve_settings
from app.vault.store import SecretStore

log = structlog.get_logger()

type AccountChecker = Callable[[Settings, AccountType], Awaitable[BrokerAccount]]


class DerivCheckProblem(DomainError):
    """Base of the reasons a check could not say which account a token opens."""


class DerivNotConfiguredError(DerivCheckProblem):
    """The app id or the token of that account is not stored (nor in `backend/.env`)."""


class DerivRefusedError(DerivCheckProblem):
    """Deriv refused the token, or it has no account of that kind."""


class DerivUnreachableError(DerivCheckProblem):
    """Deriv could not be reached or answered something unreadable."""


@dataclass(slots=True, frozen=True)
class DerivAssets:
    available: bool
    reason: str | None  # why there is no list, in words
    assets: list[AssetOffer]


_TOKEN = {AccountType.DEMO: "deriv_token_demo", AccountType.REAL: "deriv_token_real"}


class DerivService:
    def __init__(
        self,
        *,
        vault: SecretStore,
        settings: Callable[[], Settings],
        checker: AccountChecker,
        engine: Callable[[], Engine | None],
    ) -> None:
        self._vault = vault
        self._settings = settings
        self._checker = checker
        self._engine = engine

    async def check(self, account_type: AccountType) -> BrokerAccount:
        """Which Deriv account the stored token of `account_type` opens. Nothing is traded."""
        try:
            settings = await resolve_settings(self._settings(), self._vault, allow_real=False)
        except EngineStartError as exc:
            raise DerivNotConfiguredError(str(exc)) from exc
        token = getattr(settings, _TOKEN[account_type])
        if not (settings.deriv_app_id or "").strip():
            raise DerivNotConfiguredError("The Deriv app id is not stored yet.")
        if token is None or not token.get_secret_value().strip():
            raise DerivNotConfiguredError(
                f"The Deriv {account_type.value} token is not stored yet."
            )
        try:
            account = await self._checker(settings, account_type)
        except LoginRejectedError as exc:
            raise DerivRefusedError(str(exc)) from exc
        except BrokerConnectionError as exc:
            raise DerivUnreachableError(str(exc)) from exc
        except BrokerError as exc:
            raise DerivRefusedError(str(exc)) from exc
        log.info("deriv_token_checked", account_type=account_type.value)
        return account

    def assets(self) -> DerivAssets:
        """Deriv's assets as the running engine knows them."""
        engine = self._engine()
        if engine is None:
            return DerivAssets(False, "The trading engine is not running.", [])
        adapter = engine.adapters.get(Broker.DERIV)
        if adapter is None:
            return DerivAssets(
                False, "Deriv is not set up: its app id or demo token is missing.", []
            )
        if adapter.state is not ConnectionState.CONNECTED:
            return DerivAssets(False, "Deriv is not connected.", [])
        return DerivAssets(True, None, adapter.catalogue())
