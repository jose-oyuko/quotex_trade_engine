"""Opening the application's encrypted store from the command-line tools, so that they read and
write the same logins as the dashboard (decision D-67) instead of a file or `.env` of their own."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import SystemClock
from app.core.config import Settings
from app.db.engine import create_engine, create_session_factory
from app.db.migrations import schema_is_current
from app.engine.flags import EngineFlags
from app.engine.logins import resolve_settings
from app.vault.crypto import Cipher
from app.vault.store import SecretStore


class StoreUnavailableError(Exception):
    """The store cannot be opened; the message says what to do."""


@dataclass(slots=True)
class Store:
    engine: AsyncEngine
    vault: SecretStore
    flags: EngineFlags

    async def close(self) -> None:
        await self.engine.dispose()


async def open_store(settings: Settings) -> Store:
    """The vault of this installation. Raises `StoreUnavailableError` if there is no database yet,
    it is out of date, or there is no usable `SECRET_KEY`."""
    if not settings.database_path.exists():
        raise StoreUnavailableError(
            "There is no database yet: run `npm start` once (it prepares everything), then try "
            "again."
        )
    engine = create_engine(settings.database_url)
    try:
        if not await schema_is_current(engine):
            raise StoreUnavailableError("The database is out of date: run `npm run db:upgrade`.")
        cipher = Cipher(settings.secret_key.get_secret_value() if settings.secret_key else None)
        if cipher.status() != "ok":
            raise StoreUnavailableError(
                "SECRET_KEY in backend/.env is missing or not valid: run `npm run key:create`."
            )
    except BaseException:
        await engine.dispose()
        raise
    clock = SystemClock()
    factory = create_session_factory(engine)
    return Store(engine, SecretStore(factory, cipher, clock), EngineFlags(factory, clock))


async def with_stored_logins(settings: Settings) -> Settings:
    """`settings` with the logins stored on the dashboard filled in. Without a usable store (a
    new installation, no key) the settings come back unchanged: `.env` alone is used, as before."""
    try:
        store = await open_store(settings)
    except StoreUnavailableError:
        return settings
    try:
        return await resolve_settings(settings, store.vault, allow_real=False)
    finally:
        await store.close()
