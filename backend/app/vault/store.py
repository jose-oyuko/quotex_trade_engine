"""The secrets the dashboard stores, encrypted, in the database.

The API only ever learns whether a secret is set and whether it can be read; the value goes in and
never comes out through it. (Later phases read values inside the process, with `get`, to log in to
Quotex and Telegram.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.db.models import StoredSecret
from app.vault.crypto import Cipher
from app.vault.errors import (
    InvalidSecretError,
    SecretUnreadableError,
    UnknownSecretError,
    VaultError,
)

log = structlog.get_logger()

MAX_VALUE_LENGTH = 512


@dataclass(slots=True, frozen=True)
class SecretKind:
    name: str
    label: str
    help: str


# The secrets the owner may store through the dashboard. Later phases add the Telegram and Quotex
# sessions, which only the application itself writes.
KINDS: tuple[SecretKind, ...] = (
    SecretKind("quotex_email", "Quotex email", "The email you log in to Quotex with."),
    SecretKind("quotex_password", "Quotex password", "Your Quotex password."),
    SecretKind(
        "telegram_api_hash",
        "Telegram API hash",
        "From https://my.telegram.org, 'API development tools'.",
    ),
)
KIND_BY_NAME = {kind.name: kind for kind in KINDS}


@dataclass(slots=True, frozen=True)
class SecretStatus:
    name: str
    label: str
    help: str
    set: bool
    readable: bool
    updated_at: datetime | None


@dataclass(slots=True, frozen=True)
class VaultStatus:
    key: str  # `ok`, `missing` or `invalid`
    secrets: list[SecretStatus]


def _kind(name: str) -> SecretKind:
    kind = KIND_BY_NAME.get(name)
    if kind is None:
        raise UnknownSecretError(f"There is no secret called {name!r}.")
    return kind


class SecretStore:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], cipher: Cipher, clock: Clock
    ) -> None:
        self._sessions = session_factory
        self._cipher = cipher
        self._clock = clock

    async def status(self) -> VaultStatus:
        """What is stored, without any value. `readable` is False when the key is missing or is not
        the one the value was stored with."""
        async with self._sessions() as session:
            rows = {row.name: row for row in await session.scalars(select(StoredSecret))}
        key = self._cipher.status()
        items: list[SecretStatus] = []
        for kind in KINDS:
            row = rows.get(kind.name)
            readable = False
            if row is not None and key == "ok":
                try:
                    self._cipher.decrypt(kind.name, row.ciphertext)
                    readable = True
                except SecretUnreadableError:
                    readable = False
            items.append(
                SecretStatus(
                    kind.name,
                    kind.label,
                    kind.help,
                    row is not None,
                    readable,
                    row.updated_at if row else None,
                )
            )
        return VaultStatus(key, items)

    async def put(self, name: str, value: str) -> None:
        """Store `value` (replacing any earlier one, readable or not)."""
        kind = _kind(name)
        value = value.strip() if name == "quotex_email" else value
        if not value or not value.strip():
            raise InvalidSecretError(f"{kind.label} must not be empty.")
        if len(value) > MAX_VALUE_LENGTH or "\x00" in value:
            raise InvalidSecretError(f"{kind.label} is too long or contains an invalid character.")
        sealed = self._cipher.encrypt(name, value)  # raises if the key is missing or malformed
        now = self._clock.now()
        async with self._sessions() as session, session.begin():
            row = await session.get(StoredSecret, name)
            if row is None:
                session.add(
                    StoredSecret(name=name, ciphertext=sealed, created_at=now, updated_at=now)
                )
            else:
                row.ciphertext = sealed
                row.updated_at = now
        log.info("secret_stored", name=name)  # the name only, never the value

    async def delete(self, name: str) -> None:
        _kind(name)
        async with self._sessions() as session, session.begin():
            await session.execute(delete(StoredSecret).where(StoredSecret.name == name))
        log.info("secret_removed", name=name)

    async def get(self, name: str) -> str | None:
        """The plain value, for the application's own use (never for an API answer). None if not
        set. Raises a `VaultError` if the key is missing/wrong or the value is damaged."""
        _kind(name)
        async with self._sessions() as session:
            row = await session.get(StoredSecret, name)
        if row is None:
            return None
        try:
            return self._cipher.decrypt(name, row.ciphertext)
        except VaultError:
            log.warning("secret_unreadable", name=name)
            raise
