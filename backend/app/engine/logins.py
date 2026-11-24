"""The logins the engine is built with: what was stored in the dashboard, else what `.env` has.

A stored value that cannot be read is never silently replaced by the `.env` one: the owner is told,
so a wrong key is noticed instead of the engine quietly using an older password.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
    ("quotex_session", "quotex_session", "Quotex login"),
    ("deriv_app_id", "deriv_app_id", "Deriv app id"),
    ("deriv_token_demo", "deriv_token_demo", "Deriv demo token"),
    ("deriv_token_real", "deriv_token_real", "Deriv real token"),
)
# What each broker needs before the engine can start with it (decision D-75: one is enough).
BrokerName = Literal["Deriv", "Quotex"]
BROKER_LOGINS: tuple[tuple[BrokerName, tuple[str, ...]], ...] = (
    ("Deriv", ("Deriv app id", "Deriv demo token")),
    ("Quotex", ("Quotex email", "Quotex password")),
)
_NUMBERS = {"telegram_api_id"}
_TEXTS = {"deriv_app_id"}  # plain text in `Settings`, not a `SecretStr`


@dataclass(slots=True, frozen=True)
class LoginItem:
    label: str
    present: bool
    source: str  # `dashboard`, `.env`, `.session file`, `missing` or `unreadable`
    required: bool = True  # the engine cannot start without it (Telegram is optional, D-71)


async def resolve_settings(settings: Settings, vault: SecretStore, *, allow_real: bool) -> Settings:
    """`settings` with the stored logins filled in, and the owner's real-money permission."""
    updates: dict[str, object] = {"quotex_allow_real": allow_real}
    for name, field, label in STORED_LOGINS:
        try:
            value = await vault.get(name)
        except VaultError as exc:
            raise EngineStartError(f"The stored {label} cannot be used: {exc}") from exc
        if value:
            if name in _NUMBERS:
                updates[field] = int(value)
            elif name in _TEXTS:
                updates[field] = value.strip()
            else:
                updates[field] = SecretStr(value)
    return settings.model_copy(update=updates)


def _env_has(settings: Settings, field: str) -> bool:
    value = getattr(settings, field)
    if value is None:
        return False
    return bool(value.get_secret_value().strip()) if isinstance(value, SecretStr) else True


async def login_items(settings: Settings, vault: SecretStore) -> list[LoginItem]:
    """Which logins the engine would have, and where each comes from (never the values). One
    broker is enough (decision D-75): Quotex's email and password are needed only without Deriv's
    app id and demo token, and the other way round."""
    status = {item.name: item for item in (await vault.status()).secrets}

    def ready(*names: str) -> bool:
        return all(
            (status[name].set and status[name].readable) or _env_has(settings, name)
            for name in names
        )

    deriv_ready = ready("deriv_app_id", "deriv_token_demo")
    quotex_ready = ready("quotex_email", "quotex_password")
    items: list[LoginItem] = []
    for name, field, label in STORED_LOGINS:
        if name == "telegram_session":
            items.append(await _telegram_login(settings, vault))
            continue
        if name == "quotex_session":
            items.append(await _quotex_login(settings, vault))
            continue
        stored = status[name]
        # Telegram is optional (decision D-71); one broker is enough (D-75), and Deriv's real
        # token is never needed
        if name.startswith("telegram") or name == "deriv_token_real":
            needed = False
        elif name.startswith("deriv"):
            needed = not quotex_ready
        else:
            needed = not deriv_ready
        if stored.set and stored.readable:
            items.append(LoginItem(label, True, "dashboard", required=needed))
        elif stored.set:
            items.append(LoginItem(label, False, "unreadable", required=needed))
        elif _env_has(settings, field):
            items.append(LoginItem(label, True, ".env", required=needed))
        else:
            items.append(LoginItem(label, False, "missing", required=needed))
    return items


@dataclass(slots=True, frozen=True)
class BrokerChoice:
    """A broker the engine could start with, and the logins it still lacks."""

    broker: BrokerName
    missing: tuple[str, ...]


def broker_choices(items: list[LoginItem]) -> list[BrokerChoice]:
    """Empty when some broker has all it needs. Otherwise one entry per broker with only the
    pieces still missing, the closest broker first: adding those of any ONE broker is enough."""
    present = {item.label for item in items if item.present}
    choices = [
        BrokerChoice(broker, tuple(label for label in labels if label not in present))
        for broker, labels in BROKER_LOGINS
    ]
    if any(not choice.missing for choice in choices):
        return []
    return sorted(choices, key=lambda choice: len(choice.missing))


async def _quotex_login(settings: Settings, vault: SecretStore) -> LoginItem:
    """The Quotex login made on the dashboard. Not required: without it the engine logs in with the
    email and password, which only fails if Quotex asks for an e-mailed PIN."""
    label = "Quotex login"
    if await vault.has("quotex_session"):
        try:
            await vault.get("quotex_session")
        except VaultError:
            return LoginItem(label, False, "unreadable", required=False)
        return LoginItem(label, True, "dashboard", required=False)
    if _env_has(settings, "quotex_session"):
        return LoginItem(label, True, ".env", required=False)
    return LoginItem(label, False, "missing", required=False)


async def _telegram_login(settings: Settings, vault: SecretStore) -> LoginItem:
    """Not required: without it the engine starts with signals off, and trading sessions (which
    need Quotex only) still run."""
    label = "Telegram login"
    if await vault.has("telegram_session"):
        try:
            await vault.get("telegram_session")
        except VaultError:
            return LoginItem(label, False, "unreadable", required=False)
        return LoginItem(label, True, "dashboard", required=False)
    if _env_has(settings, "telegram_session"):
        return LoginItem(label, True, ".env", required=False)
    path = settings.telegram_session_path
    if path.with_name(path.name + ".session").is_file():
        return LoginItem(label, True, ".session file", required=False)
    return LoginItem(label, False, "missing", required=False)
