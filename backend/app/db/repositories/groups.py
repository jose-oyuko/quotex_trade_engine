from __future__ import annotations

from dataclasses import replace

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, GroupSettings
from app.db.repositories._mapping import to_record, to_values
from app.domain.records import GroupRecord, GroupSettingsRecord


class GroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, group: GroupRecord) -> GroupRecord:
        """Insert a group; returns it with the database-assigned id."""
        row = Group(**{k: v for k, v in to_values(group).items() if k != "id"})
        self._session.add(row)
        await self._session.flush()
        return replace(group, id=row.id)

    async def get(self, group_id: int) -> GroupRecord | None:
        row = await self._session.get(Group, group_id)
        return to_record(GroupRecord, row) if row else None

    async def get_by_chat_id(self, telegram_chat_id: int) -> GroupRecord | None:
        row = await self._session.scalar(
            select(Group).where(Group.telegram_chat_id == telegram_chat_id)
        )
        return to_record(GroupRecord, row) if row else None

    async def list_all(self, *, enabled_only: bool = False) -> list[GroupRecord]:
        stmt = select(Group).order_by(Group.id)
        if enabled_only:
            stmt = stmt.where(Group.enabled.is_(True))
        return [to_record(GroupRecord, row) for row in await self._session.scalars(stmt)]

    async def update(self, group: GroupRecord) -> None:
        """Update title and enabled flag. Raises LookupError if the group does not exist."""
        row = await self._session.get(Group, group.id)
        if row is None:
            raise LookupError(f"group {group.id} not found")
        row.title = group.title
        row.enabled = group.enabled
        row.updated_at = group.updated_at
        await self._session.flush()

    async def delete(self, group_id: int) -> bool:
        """Delete a group and its settings. Fails (IntegrityError) if signals, chains or trades
        still refer to it: disable the group instead."""
        await self._session.execute(delete(GroupSettings).where(GroupSettings.group_id == group_id))
        result = await self._session.execute(delete(Group).where(Group.id == group_id))
        await self._session.flush()
        return result.rowcount > 0  # type: ignore[attr-defined, no-any-return]

    async def save_settings(self, settings: GroupSettingsRecord) -> None:
        await self._session.merge(GroupSettings(**to_values(settings)))
        await self._session.flush()

    async def get_settings(self, group_id: int) -> GroupSettingsRecord | None:
        row = await self._session.get(GroupSettings, group_id)
        return to_record(GroupSettingsRecord, row) if row else None

    async def list_settings(self) -> list[GroupSettingsRecord]:
        rows = await self._session.scalars(select(GroupSettings).order_by(GroupSettings.group_id))
        return [to_record(GroupSettingsRecord, row) for row in rows]
