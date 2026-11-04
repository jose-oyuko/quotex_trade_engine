"""The seam between our code and the Telegram library.

`TelegramSource` is the small interface the listener and the login script need. The only real
implementation is `TelethonSource` (the only module importing Telethon, as `app/quotex` does for
pyquotex); `FakeTelegramSource` drives the tests. Console input never happens here: the login
script collects the code and password and passes them in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.core.errors import DomainError
from app.signals.models import RawMessage

type MessageHandler = Callable[[RawMessage], None]


class TelegramError(DomainError):
    """Base class for Telegram problems."""


class TelegramNotConfiguredError(TelegramError):
    """TELEGRAM_API_ID / TELEGRAM_API_HASH are missing."""


class TelegramLoginError(TelegramError):
    """The phone number, code or password was refused (or Telegram asks us to wait)."""


class PasswordRequiredError(TelegramLoginError):
    """The account has two-step verification: the code was accepted, a password is also needed."""


class PhoneInvalidError(TelegramLoginError):
    """Telegram does not accept the phone number."""


class ApiCredentialsError(TelegramLoginError):
    """Telegram rejected the API id / hash."""


class CodeInvalidError(TelegramLoginError):
    """The code is wrong; the same code request can be answered again."""


class CodeExpiredError(TelegramLoginError):
    """The code is too old: a new one has to be requested."""


class PasswordInvalidError(TelegramLoginError):
    """The two-step verification password is wrong."""


class FloodWaitLoginError(TelegramLoginError):
    """Telegram asks us to wait before trying again."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"too many attempts: wait {seconds} s and retry")
        self.seconds = seconds


class DialogKind(StrEnum):
    GROUP = "group"
    CHANNEL = "channel"
    USER = "user"


@dataclass(slots=True, frozen=True)
class DialogInfo:
    """A chat the account can see. `chat_id` is the id messages arrive with (channels and
    supergroups look like -1001234567890) and is what `GroupRecord.telegram_chat_id` stores."""

    chat_id: int
    title: str
    kind: DialogKind


class TelegramSource(Protocol):
    def set_handler(self, handler: MessageHandler) -> None:
        """Where incoming messages (new and edited) of the subscribed chats are delivered."""
        ...

    def set_chats(self, chat_ids: frozenset[int]) -> None:
        """Replace the set of chats to deliver messages from. Takes effect at once, no reconnect."""
        ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def is_authorized(self) -> bool:
        """True if the saved session is logged in. Call after `connect`."""
        ...

    async def request_code(self, phone: str) -> str:
        """Ask Telegram to send a login code. Returns where Telegram says it went, in words
        ("to your Telegram app", "by SMS", ...), so the person knows where to look."""
        ...

    async def resend_code(self, phone: str) -> str:
        """Ask Telegram to send the same login attempt's code another way (usually SMS).
        Returns where it went, like `request_code`. Raises `TelegramLoginError` if Telegram has
        no other way left to try."""
        ...

    async def sign_in(self, phone: str, code: str) -> None:
        """Raises `PasswordRequiredError` if two-step verification is on, `TelegramLoginError`
        for a wrong or expired code."""
        ...

    async def sign_in_password(self, password: str) -> None: ...

    async def list_dialogs(self) -> list[DialogInfo]: ...

    def session_string(self) -> str | None:
        """The logged-in session as text (to store, encrypted), or None if the source keeps its
        session somewhere else (a file)."""
        ...

    async def log_out(self) -> None:
        """End this login on Telegram's side too."""
        ...

    async def wait_disconnected(self) -> None:
        """Returns when the connection has been lost (after the library's own retries) or closed."""
        ...
