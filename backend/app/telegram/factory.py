"""Builds the real Telegram source from the application settings."""

from __future__ import annotations

from app.core.clock import Clock
from app.core.config import Settings
from app.telegram.source import TelegramNotConfiguredError
from app.telegram.telethon_source import TelethonSource


def build_telethon_source(settings: Settings, *, clock: Clock) -> TelethonSource:
    api_hash = (
        settings.telegram_api_hash.get_secret_value().strip() if settings.telegram_api_hash else ""
    )
    if settings.telegram_api_id is None or not api_hash:
        raise TelegramNotConfiguredError(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in backend/.env "
            "(create them at https://my.telegram.org, 'API development tools')"
        )
    return TelethonSource(
        api_id=settings.telegram_api_id,
        api_hash=api_hash,
        session_path=settings.telegram_session_path,
        clock=clock,
    )
