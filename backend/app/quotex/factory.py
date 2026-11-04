"""Builds the real adapter from the application settings."""

from __future__ import annotations

from app.core.clock import Clock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.domain.enums import AccountType
from app.events.bus import EventBus
from app.quotex.base import LoginRequest, QuotexLogin
from app.quotex.errors import QuotexError
from app.quotex.pyquotex_adapter import PyQuotexAdapter
from app.quotex.pyquotex_client import OtpCallback, PyQuotexClient, refuse_pin
from app.quotex.pyquotex_login import PyQuotexLogin


def build_pyquotex_adapter(
    settings: Settings,
    *,
    tasks: TaskSupervisor,
    clock: Clock,
    bus: EventBus | None = None,
    account_type: AccountType = AccountType.DEMO,
    otp_callback: OtpCallback = refuse_pin,
) -> PyQuotexAdapter:
    """The adapter starts on the DEMO account; REAL is only possible if `QUOTEX_ALLOW_REAL=true`."""
    email = settings.quotex_email.get_secret_value().strip() if settings.quotex_email else ""
    password = settings.quotex_password.get_secret_value() if settings.quotex_password else ""
    if not email or not password:  # a blank value in .env counts as missing
        raise QuotexError(
            "The Quotex email and password are not set. Store them under Settings > Stored logins "
            "(or as QUOTEX_EMAIL and QUOTEX_PASSWORD in backend/.env)."
        )

    session = (
        settings.quotex_session.get_secret_value().strip() if settings.quotex_session else None
    )

    def make_client() -> PyQuotexClient:
        return PyQuotexClient(
            email=email,
            password=password,
            host=settings.quotex_host,
            data_dir=settings.data_dir.resolve(),
            time_mode=settings.quotex_time_mode,
            otp_callback=otp_callback,
            session=session or None,
        )

    return PyQuotexAdapter(
        make_client,
        tasks=tasks,
        clock=clock,
        bus=bus,
        account_type=account_type,
        allow_real=settings.quotex_allow_real,
    )


def new_quotex_login(request: LoginRequest) -> QuotexLogin:
    """The login the dashboard uses (a private temporary folder; see `pyquotex_login`)."""
    return PyQuotexLogin(request)
