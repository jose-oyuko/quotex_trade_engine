"""The real Telegram connection, through Telethon. The only module that imports it.

Telethon is asyncio-native, so it runs on the application's own event loop. It reconnects by
itself after a drop and gives up only after its retries; the listener then reconnects with backoff
(`TelegramListener`). Messages are filtered by chat id in `set_chats` rather than by Telethon's own
`chats=` argument, so chats can be added and removed while running without touching the handlers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from telethon import TelegramClient, errors, events, functions

from app.core.clock import Clock
from app.signals.models import RawMessage
from app.telegram.source import (
    DialogInfo,
    DialogKind,
    MessageHandler,
    PasswordRequiredError,
    TelegramError,
    TelegramLoginError,
)

log = structlog.get_logger()


def raw_from_event(event: Any, *, edited: bool, clock: Clock) -> RawMessage | None:
    """Telethon event -> `RawMessage`. Returns None for events without a chat or a message."""
    message = getattr(event, "message", None)
    chat_id = getattr(event, "chat_id", None)
    if message is None or chat_id is None:
        return None
    return RawMessage(
        chat_id=int(chat_id),
        message_id=getattr(message, "id", None),
        text=getattr(message, "message", None) or "",
        received_at=clock.now(),
        received_ns=clock.monotonic_ns(),
        sent_at=getattr(message, "date", None),
        edited=edited,
    )


def dialog_info(dialog: Any) -> DialogInfo:
    if dialog.is_user:
        kind = DialogKind.USER
    elif dialog.is_group:
        kind = DialogKind.GROUP
    else:
        kind = DialogKind.CHANNEL
    return DialogInfo(chat_id=int(dialog.id), title=str(dialog.name or ""), kind=kind)


_DELIVERY = {
    "SentCodeTypeApp": "to your Telegram app (a message from the chat named 'Telegram')",
    "SentCodeTypeSms": "by SMS",
    "SentCodeTypeFirebaseSms": "by SMS",
    "SentCodeTypeSmsWord": "by SMS (the code is a word)",
    "SentCodeTypeSmsPhrase": "by SMS (the code is a phrase)",
    "SentCodeTypeFragmentSms": "as a message on fragment.com",
    "SentCodeTypeCall": "by a phone call that reads it out",
    "SentCodeTypeFlashCall": "as a short phone call: the code is the number it calls from",
    "SentCodeTypeMissedCall": "as a missed call: the code is the last digits of the number",
    "SentCodeTypeEmailCode": "to your e-mail address",
}


def describe_code_delivery(sent: Any) -> str:
    """Words for where Telegram says the login code went (`SentCode.type`)."""
    kind = type(getattr(sent, "type", None)).__name__
    return _DELIVERY.get(kind, f"in a way this program does not know ({kind})")


class TelethonSource:
    def __init__(self, *, api_id: int, api_hash: str, session_path: Path, clock: Clock) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._session_path = session_path
        self._clock = clock
        self._client: Any = None
        self._handler: MessageHandler | None = None
        self._chats: frozenset[int] = frozenset()
        self._code_hash: str | None = None  # identifies the login attempt Telegram started

    def set_handler(self, handler: MessageHandler) -> None:
        self._handler = handler

    def set_chats(self, chat_ids: frozenset[int]) -> None:
        self._chats = chat_ids

    async def connect(self) -> None:
        if self._client is None:
            self._session_path.parent.mkdir(parents=True, exist_ok=True)
            self._client = TelegramClient(str(self._session_path), self._api_id, self._api_hash)
            self._client.add_event_handler(self._on_new, events.NewMessage())
            self._client.add_event_handler(self._on_edited, events.MessageEdited())
        try:
            await self._client.connect()
        except (OSError, TimeoutError, errors.RPCError) as exc:
            raise TelegramError(f"cannot connect to Telegram: {type(exc).__name__}: {exc}") from exc

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()

    async def is_authorized(self) -> bool:
        return bool(await self._client.is_user_authorized())

    async def request_code(self, phone: str) -> str:
        try:
            sent = await self._client.send_code_request(phone)
        except errors.PhoneNumberInvalidError as exc:
            raise TelegramLoginError(
                "Telegram does not accept that phone number: use the international format "
                "+<country code><number>, with no leading 0"
            ) from exc
        except errors.ApiIdInvalidError as exc:
            raise TelegramLoginError(
                "Telegram rejected TELEGRAM_API_ID / TELEGRAM_API_HASH: copy them again from "
                "https://my.telegram.org (API development tools) into backend/.env"
            ) from exc
        except errors.FloodWaitError as exc:
            raise TelegramLoginError(f"too many attempts: wait {exc.seconds} s and retry") from exc
        self._code_hash = sent.phone_code_hash
        return describe_code_delivery(sent)

    async def resend_code(self, phone: str) -> str:
        if self._code_hash is None:
            raise TelegramLoginError("no login code was requested yet")
        try:
            sent = await self._client(
                functions.auth.ResendCodeRequest(
                    phone_number=phone, phone_code_hash=self._code_hash
                )
            )
        except errors.SendCodeUnavailableError as exc:
            raise TelegramLoginError(
                "Telegram has no other way to send the code right now: wait a few minutes "
                "and run the login again"
            ) from exc
        except errors.FloodWaitError as exc:
            raise TelegramLoginError(f"too many attempts: wait {exc.seconds} s and retry") from exc
        self._code_hash = sent.phone_code_hash
        return describe_code_delivery(sent)

    async def sign_in(self, phone: str, code: str) -> None:
        try:
            await self._client.sign_in(phone, code, phone_code_hash=self._code_hash)
        except errors.SessionPasswordNeededError as exc:
            raise PasswordRequiredError(
                "two-step verification is on: a password is needed"
            ) from exc
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError) as exc:
            raise TelegramLoginError("the code is wrong or has expired") from exc
        except errors.FloodWaitError as exc:
            raise TelegramLoginError(f"too many attempts: wait {exc.seconds} s and retry") from exc

    async def sign_in_password(self, password: str) -> None:
        try:
            await self._client.sign_in(password=password)
        except errors.PasswordHashInvalidError as exc:
            raise TelegramLoginError("the two-step verification password is wrong") from exc

    async def list_dialogs(self) -> list[DialogInfo]:
        return [dialog_info(dialog) for dialog in await self._client.get_dialogs()]

    async def wait_disconnected(self) -> None:
        await self._client.disconnected

    # --- Telethon callbacks ---

    async def _on_new(self, event: Any) -> None:
        self._deliver(event, edited=False)

    async def _on_edited(self, event: Any) -> None:
        self._deliver(event, edited=True)

    def _deliver(self, event: Any, *, edited: bool) -> None:
        if self._handler is None:
            return
        chat_id = getattr(event, "chat_id", None)
        if chat_id is None or int(chat_id) not in self._chats:
            return
        raw = raw_from_event(event, edited=edited, clock=self._clock)
        if raw is None:
            return
        try:
            self._handler(raw)
        except Exception:
            # Telethon would only log it; our handler must never take the update loop down.
            log.exception("telegram_handler_failed", chat_id=raw.chat_id)
