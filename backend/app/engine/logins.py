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

# (secret name, Settings field, label). The Telegram login is a session made on the dashboard.
STORED_LOGINS = (
    ("quotex_email", "quotex_email", "Quotex email"),
    ("quotex_password", "quotex_password", "Quotex password"),
    ("telegram_api_id", "telegram_api_id", "Telegram API id"),
    ("telegram_api_hash", "telegram_api_hash", "Telegram API hash"),
    ("telegram_session", "telegram_session", "Telegram login"),
)
_NUMBERS = {"telegram_api_id"}


@dataclass(slots=True, frozen=True)
class LoginItem:
    label: str
    present: bool
    source: str  # `dashboard`, `.env`, `.session file`, `missing` or `unreadable`


async def resolve_settings(settings: Settings, vault: SecretStore, *, allow_real: bool) -> Settings:
    """`settings` with the stored logins filled in, and the owner's real-money permission."""
    updates: dict[str, object] = {"quotex_allow_real": allow_real}
    for name, field, label in STORED_LOGINS:
        try:
            value = await vault.get(name)
        except VaultError as exc:
            raise EngineStartError(f"The stored {label} cannot be used: {exc}") from exc
        if value:
            updates[field] = int(value) if name in _NUMBERS else SecretStr(value)
    return settings.model_copy(update=updates)


def _env_has(settings: Settings, field: str) -> bool:
    value = getattr(settings, field)
    if value is None:
        return False
    return bool(value.get_secret_value().strip()) if isinstance(value, SecretStr) else True


async def login_items(settings: Settings, vault: SecretStore) -> list[LoginItem]:
    """Which logins the engine would have, and where each comes from (never the values)."""
    status = {item.name: item for item in (await vault.status()).secrets}
    items: list[LoginItem] = []
    for name, field, label in STORED_LOGINS:
        if name == "telegram_session":
            items.append(await _telegram_login(settings, vault))
            continue
        stored = status[name]
        if stored.set and stored.readable:
            items.append(LoginItem(label, True, "dashboard"))
        elif stored.set:
            items.append(LoginItem(label, False, "unreadable"))
        elif _env_has(settings, field):
            items.append(LoginItem(label, True, ".env"))
        else:
            items.append(LoginItem(label, False, "missing"))
    return items


async def _telegram_login(settings: Settings, vault: SecretStore) -> LoginItem:
    label = "Telegram login"
    if await vault.has("telegram_session"):
        try:
            await vault.get("telegram_session")
        except VaultError:
            return LoginItem(label, False, "unreadable")
        return LoginItem(label, True, "dashboard")
    if _env_has(settings, "telegram_session"):
        return LoginItem(label, True, ".env")
    path = settings.telegram_session_path
    if path.with_name(path.name + ".session").is_file():
        return LoginItem(label, True, ".session file")
    return LoginItem(label, False, "missing")
