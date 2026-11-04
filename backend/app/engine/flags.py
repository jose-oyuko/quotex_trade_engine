"""What the owner decided about the engine, remembered in the database (decision D-63)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.db.repositories import AppSettingsRepository

KEY_DESIRED = "engine.desired"  # True: start the engine when the application starts
KEY_ALLOW_REAL = "engine.allow_real"  # True: switching to the REAL account is permitted


class EngineFlags:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessions = session_factory
        self._clock = clock

    async def _get(self, key: str) -> bool | None:
        async with self._sessions() as session:
            row = await AppSettingsRepository(session).get(key)
        return row.value if row is not None and isinstance(row.value, bool) else None

    async def _set(self, key: str, value: bool) -> None:
        async with self._sessions() as session, session.begin():
            await AppSettingsRepository(session).set(key, value, now=self._clock.now())

    async def desired(self) -> bool | None:
        """Whether the owner left the engine running; None if they never decided."""
        return await self._get(KEY_DESIRED)

    async def set_desired(self, value: bool) -> None:
        await self._set(KEY_DESIRED, value)

    async def allow_real(self) -> bool | None:
        return await self._get(KEY_ALLOW_REAL)

    async def set_allow_real(self, value: bool) -> None:
        await self._set(KEY_ALLOW_REAL, value)
