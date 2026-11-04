"""The logins the engine is built with: what was stored in the dashboard, else what `.env` has.

A stored value that cannot be read is never silently replaced by the `.env` one: the owner is told,
so a wrong key is noticed instead of the engine quietly using an older password.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr

from app.core.config import Settings
from app.engine.errors import EngineStartError
from app.vault.errors import VaultError
from app.vault.store import SecretStore

# (secret name, Settings field, label). The Telegram API id and phone are not secrets and still come
# from `.env` until the Telegram login moves to the dashboard.
STORED_LOGINS = (
    ("quotex_email", "quotex_email", "Quotex email"),
    ("quotex_password", "quotex_password", "Quotex password"),
    ("telegram_api_hash", "telegram_api_hash", "Telegram API hash"),
)


@dataclass(slots=True, frozen=True)
class LoginItem:
    label: str
    present: bool
    source: str  # `dashboard`, `.env` or `missing`


async def resolve_settings(settings: Settings, vault: SecretStore, *, allow_real: bool) -> Settings:
    """`settings` with the stored logins filled in, and the owner's real-money permission."""
    updates: dict[str, object] = {"quotex_allow_real": allow_real}
    for name, field, label in STORED_LOGINS:
        try:
            value = await vault.get(name)
        except VaultError as exc:
            raise EngineStartError(f"The stored {label} cannot be used: {exc}") from exc
        if value:
            updates[field] = SecretStr(value)
    return settings.model_copy(update=updates)


async def login_items(settings: Settings, vault: SecretStore) -> list[LoginItem]:
    """Which logins the engine would have, and where each comes from (never the values)."""
    items: list[LoginItem] = []
    status = {item.name: item for item in (await vault.status()).secrets}
    for name, field, label in STORED_LOGINS:
        stored = status[name]
        env_value = getattr(settings, field)
        if stored.set and stored.readable:
            items.append(LoginItem(label, True, "dashboard"))
        elif env_value is not None and env_value.get_secret_value().strip() and not stored.set:
            items.append(LoginItem(label, True, ".env"))
        else:
            items.append(LoginItem(label, False, "unreadable" if stored.set else "missing"))
    items.append(
        LoginItem(
            "Telegram API id",
            settings.telegram_api_id is not None,
            ".env" if settings.telegram_api_id is not None else "missing",
        )
    )
    return items
