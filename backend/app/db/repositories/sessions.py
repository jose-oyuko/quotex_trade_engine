from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionRun, TradingSession
from app.db.repositories._mapping import page, to_record, to_values
from app.domain.enums import RunState
from app.domain.records import SessionRecord, SessionRunRecord


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- the sessions themselves ---

    async def add(self, record: SessionRecord) -> SessionRecord:
        """Insert a session; returns it with the database-assigned id."""
        row = TradingSession(**{k: v for k, v in to_values(record).items() if k != "id"})
        self._session.add(row)
        await self._session.flush()
        return replace(record, id=row.id)

    async def update(self, record: SessionRecord) -> None:
        """Raises LookupError if the session does not exist."""
        row = await self._session.get(TradingSession, record.id)
        if row is None:
            raise LookupError(f"session {record.id} not found")
        for key, value in to_values(record).items():
            if key not in ("id", "created_at", "group_id"):
                setattr(row, key, value)
        await self._session.flush()

    async def get(self, session_id: int) -> SessionRecord | None:
        row = await self._session.get(TradingSession, session_id)
        return to_record(SessionRecord, row) if row else None

    async def list_all(self) -> list[SessionRecord]:
        rows = await self._session.scalars(select(TradingSession).order_by(TradingSession.id))
        return [to_record(SessionRecord, row) for row in rows]

    async def delete(self, session_id: int) -> bool:
        """Delete a session. Fails (IntegrityError) if runs or chains still refer to it."""
        row = await self._session.get(TradingSession, session_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    # --- runs ---

    async def upsert_run(self, run: SessionRunRecord) -> None:
        await self._session.merge(SessionRun(**to_values(run)))
        await self._session.flush()

    async def get_run(self, run_id: UUID) -> SessionRunRecord | None:
        row = await self._session.get(SessionRun, run_id)
        return to_record(SessionRunRecord, row) if row else None

    async def list_runs(
        self, *, session_id: int | None = None, limit: int = 100, offset: int = 0
    ) -> list[SessionRunRecord]:
        """Newest first."""
        limit, offset = page(limit, offset)
        stmt = select(SessionRun)
        if session_id is not None:
            stmt = stmt.where(SessionRun.session_id == session_id)
        stmt = (
            stmt.order_by(SessionRun.started_at.desc(), SessionRun.id).limit(limit).offset(offset)
        )
        return [to_record(SessionRunRecord, row) for row in await self._session.scalars(stmt)]

    async def count_runs(self, *, session_id: int | None = None) -> int:
        stmt = select(func.count()).select_from(SessionRun)
        if session_id is not None:
            stmt = stmt.where(SessionRun.session_id == session_id)
        return await self._session.scalar(stmt) or 0

    async def list_unfinished_runs(self) -> list[SessionRunRecord]:
        """Runs that were still going when the application stopped."""
        stmt = (
            select(SessionRun)
            .where(SessionRun.state.in_((RunState.RUNNING, RunState.STOPPING)))
            .order_by(SessionRun.started_at)
        )
        return [to_record(SessionRunRecord, row) for row in await self._session.scalars(stmt)]

    async def has_runs(self, session_id: int) -> bool:
        stmt = select(SessionRun.id).where(SessionRun.session_id == session_id).limit(1)
        return (await self._session.scalar(stmt)) is not None
