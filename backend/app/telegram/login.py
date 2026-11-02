"""The Telegram login flow, independent of where the code and password come from.

The terminal script gives it prompts; tests give it plain functions. Nothing here reads the
console, so it can never freeze the event loop (docs/DOMAIN.md section 6).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from app.telegram.source import PasswordRequiredError, TelegramLoginError, TelegramSource

type Ask = Callable[[str], Awaitable[str]]

_PHONE = re.compile(r"^\+[1-9]\d{6,14}$")


def normalise_phone(text: str) -> str:
    """`+254 712 345 678` -> `+254712345678`. Raises `TelegramLoginError` for anything that is not
    the international format Telegram wants (a leading 0 or a missing + are the usual mistakes)."""
    phone = re.sub(r"[\s\-().]", "", text)
    if not _PHONE.match(phone):
        raise TelegramLoginError(
            f"{text!r} is not an international phone number: write + then the country code then "
            "the number, with no leading 0 (for example +254712345678)"
        )
    return phone


RESEND_WORDS = frozenset({"sms", "resend", "again"})
MAX_RESENDS = 2


async def log_in(source: TelegramSource, *, phone: str, ask_code: Ask, ask_password: Ask) -> None:
    """Log the saved session in. Does nothing if it already is.

    Says where Telegram sent the code, and lets the person ask for it another way by typing `sms`
    instead of the code (Telegram sends it to the Telegram app first, which not everyone can see).
    """
    if await source.is_authorized():
        return
    phone = normalise_phone(phone)
    delivery = await source.request_code(phone)
    code = ""
    for resends in range(MAX_RESENDS + 1):
        answer = (
            await ask_code(
                f"Telegram says it sent the login code {delivery}.\n"
                "Type the code, or type 'sms' to ask Telegram to send it another way"
            )
        ).strip()
        if answer.lower() not in RESEND_WORDS:
            code = answer
            break
        if resends == MAX_RESENDS:
            raise TelegramLoginError("Telegram would not send the code again: try later")
        delivery = await source.resend_code(phone)
    try:
        await source.sign_in(phone, code)
    except PasswordRequiredError:
        password = await ask_password("Two-step verification password")
        await source.sign_in_password(password)
