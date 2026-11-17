"""Builds the Deriv adapter from the application settings (decision D-76)."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from app.brokers.errors import BrokerError, RealAccountNotAllowedError
from app.core.clock import Clock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.deriv.adapter import DerivAdapter
from app.deriv.login import DerivLogin
from app.domain.enums import AccountType
from app.events.bus import EventBus


def _value(secret: SecretStr | None) -> str:
    return secret.get_secret_value().strip() if secret is not None else ""


def build_deriv_adapter(
    settings: Settings,
    *,
    tasks: TaskSupervisor,
    clock: Clock,
    bus: EventBus | None = None,
    account_type: AccountType = AccountType.DEMO,
    transport: httpx.AsyncBaseTransport | None = None,
) -> DerivAdapter:
    """The adapter starts on the DEMO account; the real token is only used when real money is
    allowed and chosen. Raises `BrokerError` when the app id or the demo token is missing."""
    app_id = (settings.deriv_app_id or "").strip()
    demo_token, real_token = _value(settings.deriv_token_demo), _value(settings.deriv_token_real)
    if not app_id or not demo_token:
        raise BrokerError(
            "The Deriv app id and demo token are not set (DERIV_APP_ID and DERIV_TOKEN_DEMO in "
            "backend/.env)."
        )
    logins = {
        AccountType.DEMO: DerivLogin(
            token=demo_token, app_id=app_id, api_url=settings.deriv_api_url, transport=transport
        )
    }
    if real_token:
        logins[AccountType.REAL] = DerivLogin(
            token=real_token, app_id=app_id, api_url=settings.deriv_api_url, transport=transport
        )

    async def socket_url(kind: AccountType) -> str:
        login = logins.get(kind)
        if login is None:
            raise RealAccountNotAllowedError("no Deriv token for the real account is stored")
        return await login.socket_url(kind)

    return DerivAdapter(
        socket_url,
        tasks=tasks,
        clock=clock,
        bus=bus,
        account_type=account_type,
        allow_real=settings.quotex_allow_real,
        real_available=bool(real_token),
    )
