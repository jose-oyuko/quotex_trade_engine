"""Builds the real Telegram source from the application settings."""

from __future__ import annotations

from app.core.clock import Clock
from app.core.config import Settings
from app.telegram.source import TelegramNotConfiguredError, TelegramSource
from app.telegram.telethon_source import TelethonSource


def build_telethon_source(settings: Settings, *, clock: Clock) -> TelethonSource:
    """The source the engine uses. The login is the one made on the dashboard (a string session,
    kept encrypted in the database) or, failing that, the file the command-line login makes."""
    api_hash = (
        settings.telegram_api_hash.get_secret_value().strip() if settings.telegram_api_hash else ""
    )
    if settings.telegram_api_id is None or not api_hash:
        raise TelegramNotConfiguredError(
            "The Telegram API id and hash are not set. Store them under Settings > Telegram "
            "(create them at https://my.telegram.org, 'API development tools')."
        )
    session = (
        settings.telegram_session.get_secret_value().strip() if settings.telegram_session else ""
    )
    if session:
        return TelethonSource(
            api_id=settings.telegram_api_id, api_hash=api_hash, session_string=session, clock=clock
        )
    file = settings.telegram_session_path.with_name(
        settings.telegram_session_path.name + ".session"
    )
    if not file.is_file():
        raise TelegramNotConfiguredError(
            "Telegram is not logged in. Log in under Settings > Telegram (a phone number, then the "
            "code Telegram sends you)."
        )
    return TelethonSource(
        api_id=settings.telegram_api_id,
        api_hash=api_hash,
        session_path=settings.telegram_session_path,
        clock=clock,
    )


def new_login_source(
    api_id: int, api_hash: str, session: str | None, *, clock: Clock
) -> TelegramSource:
    """A source for logging in (or out) from the dashboard: a new session, or the saved one."""
    return TelethonSource(
        api_id=api_id, api_hash=api_hash, session_string=session or "", clock=clock
    )
