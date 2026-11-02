"""Everything Telegram-related. Only `telethon_source.py` imports Telethon."""

from app.telegram.fake import FakeTelegramSource
from app.telegram.listener import ListenerState, TelegramListener
from app.telegram.source import (
    DialogInfo,
    DialogKind,
    MessageHandler,
    PasswordRequiredError,
    TelegramError,
    TelegramLoginError,
    TelegramNotConfiguredError,
    TelegramSource,
)

__all__ = [
    "DialogInfo",
    "DialogKind",
    "FakeTelegramSource",
    "ListenerState",
    "MessageHandler",
    "PasswordRequiredError",
    "TelegramError",
    "TelegramListener",
    "TelegramLoginError",
    "TelegramNotConfiguredError",
    "TelegramSource",
]
