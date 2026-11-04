"""An in-memory Telegram for tests and demos: no network, no credentials."""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.clock import Clock
from app.signals.models import RawMessage
from app.telegram.source import (
    CodeExpiredError,
    CodeInvalidError,
    DialogInfo,
    MessageHandler,
    PasswordInvalidError,
    PasswordRequiredError,
    PhoneInvalidError,
    TelegramError,
    TelegramLoginError,
)


class FakeTelegramSource:
    """Behaves like `TelegramSource`; tests script it and push messages with `emit`."""

    def __init__(
        self,
        clock: Clock,
        *,
        dialogs: list[DialogInfo] | None = None,
        authorized: bool = True,
        login_code: str = "12345",
        two_step_password: str | None = None,
        session: str | None = None,
    ) -> None:
        self._clock = clock
        self._dialogs = dialogs or []
        self._authorized = authorized
        self._login_code = login_code
        self._two_step_password = two_step_password
        self._session = session
        self._phone: str | None = None
        self.scripted: dict[str, list[Exception]] = {}  # method name -> errors to raise, in turn
        self.logged_out = False
        self._code_requested = False
        self._code_accepted = False
        self._handler: MessageHandler | None = None
        self._chats: frozenset[int] = frozenset()
        self._connected = False
        self._lost = asyncio.Event()
        self.connect_failures = 0  # the next N calls to connect() fail
        self.connect_calls = 0
        self.resends = 0
        self.max_resends = 1  # how many times the code can be sent another way
        self.disconnect_calls = 0

    # --- test controls ---

    def emit(
        self,
        chat_id: int,
        text: str,
        *,
        message_id: int | None = 1,
        edited: bool = False,
        sent_at: datetime | None = None,
    ) -> bool:
        """Deliver a message as Telegram would. Returns False if nobody would receive it (not
        connected, no handler, or the chat is not subscribed)."""
        if not self._connected or self._handler is None or chat_id not in self._chats:
            return False
        self._handler(
            RawMessage(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                received_at=self._clock.now(),
                received_ns=self._clock.monotonic_ns(),
                sent_at=sent_at,
                edited=edited,
            )
        )
        return True

    def lose_connection(self) -> None:
        self._connected = False
        self._lost.set()

    @property
    def chats(self) -> frozenset[int]:
        return self._chats

    # --- TelegramSource ---

    def set_handler(self, handler: MessageHandler) -> None:
        self._handler = handler

    def set_chats(self, chat_ids: frozenset[int]) -> None:
        self._chats = chat_ids

    async def connect(self) -> None:
        self.connect_calls += 1
        if self.connect_failures > 0:
            self.connect_failures -= 1
            raise TelegramError("fake: cannot reach Telegram")
        self._connected = True
        self._lost = asyncio.Event()

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False
        self._lost.set()

    async def is_authorized(self) -> bool:
        return self._authorized

    def _maybe_fail(self, method: str) -> None:
        errors = self.scripted.get(method)
        if errors:
            raise errors.pop(0)

    async def request_code(self, phone: str) -> str:
        self._maybe_fail("request_code")
        if not phone.startswith("+"):
            raise PhoneInvalidError("fake: phone number must start with +")
        self._phone = phone
        self._code_requested = True
        self.resends = 0
        return "to your Telegram app"

    async def resend_code(self, phone: str) -> str:
        self._maybe_fail("resend_code")
        if not self._code_requested:
            raise TelegramLoginError("fake: no code was requested")
        if self.resends >= self.max_resends:
            raise TelegramLoginError("fake: no other way to send the code")
        self.resends += 1
        return "by SMS"

    async def sign_in(self, phone: str, code: str) -> None:
        self._maybe_fail("sign_in")
        if not self._code_requested:
            raise TelegramLoginError("fake: no code was requested")
        if code == "expired":
            raise CodeExpiredError("fake: the code has expired")
        if code != self._login_code:
            raise CodeInvalidError("fake: wrong code")
        self._code_accepted = True
        if self._two_step_password is not None:
            raise PasswordRequiredError("fake: two-step verification is on")
        self._authorized = True

    async def sign_in_password(self, password: str) -> None:
        self._maybe_fail("sign_in_password")
        if not self._code_accepted or password != self._two_step_password:
            raise PasswordInvalidError("fake: wrong password")
        self._authorized = True

    def session_string(self) -> str | None:
        if self._session is not None:
            return self._session
        return f"fake-session-for-{self._phone}" if self._authorized and self._phone else None

    async def log_out(self) -> None:
        self._maybe_fail("log_out")
        self.logged_out = True
        self._authorized = False

    def set_dialogs(self, dialogs: list[DialogInfo]) -> None:
        self._dialogs = list(dialogs)

    async def list_dialogs(self) -> list[DialogInfo]:
        return list(self._dialogs)

    async def wait_disconnected(self) -> None:
        await self._lost.wait()
