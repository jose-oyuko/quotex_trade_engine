"""Moving the logins that used to live in `backend/.env` into the encrypted store (decision D-67).

Until they are moved, a login in `.env` still works (a stored one always wins over it). Moving only
ever adds: a login that is already stored is never overwritten, and `.env` is never edited from
here (the command `npm run env:import` does that, with the owner's say-so).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import structlog
from pydantic import SecretStr

from app.core.config import Settings
from app.vault.store import SecretStore

log = structlog.get_logger()

# (secret name, Settings field, label): the logins `.env` could hold.
ENV_LOGINS = (
    ("quotex_email", "quotex_email", "Quotex email"),
    ("quotex_password", "quotex_password", "Quotex password"),
    ("telegram_api_id", "telegram_api_id", "Telegram API id"),
    ("telegram_api_hash", "telegram_api_hash", "Telegram API hash"),
)


@dataclass(slots=True, frozen=True)
class EnvLogin:
    name: str
    label: str
    in_env: bool  # `backend/.env` has a value for it
    stored: bool  # the encrypted store has one


class EnvImportService:
    def __init__(self, vault: SecretStore, settings: Callable[[], Settings]) -> None:
        self._vault = vault
        self._settings = settings

    def _env_value(self, field: str) -> str | None:
        value = getattr(self._settings(), field)
        if value is None:
            return None
        text = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        return text.strip() or None

    async def status(self) -> list[EnvLogin]:
        return [
            EnvLogin(
                name=name,
                label=label,
                in_env=self._env_value(field) is not None,
                stored=await self._vault.has(name),
            )
            for name, field, label in ENV_LOGINS
        ]

    async def import_all(self) -> list[str]:
        """Store every login that `.env` has and the store does not. Returns their labels. Raises
        the vault's errors if there is no usable `SECRET_KEY` (nothing is then stored)."""
        imported: list[str] = []
        for name, field, label in ENV_LOGINS:
            value = self._env_value(field)
            if value is None or await self._vault.has(name):
                continue
            await self._vault.put(name, value)
            imported.append(label)
        if imported:
            log.info("env_logins_imported", count=len(imported))
        return imported
