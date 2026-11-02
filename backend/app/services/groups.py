"""Creating, editing and deleting groups, and telling the running engine about it.

The database is written first; only when that has been committed is the engine told (it keeps the
group's settings in memory, ARCHITECTURE section 5). Editing a group never changes a chain that is
already running: chains snapshot their settings when they start (decision D-10).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.core.errors import DomainError
from app.db.repositories import GroupRepository
from app.domain.enums import AssetSuffixMode, Strategy
from app.domain.records import GroupRecord, GroupSettingsRecord
from app.engine.engine import Engine
from app.signals.timezones import InvalidTimezoneError, parse_timezone

log = structlog.get_logger()


class GroupError(DomainError):
    """Base class of the errors the group service raises."""


class InvalidGroupError(GroupError):
    """The values are well-formed but not acceptable (unknown parser, unknown time zone...)."""


class GroupNotFoundError(GroupError):
    pass


class GroupExistsError(GroupError):
    """A group for that Telegram chat already exists."""


class GroupInUseError(GroupError):
    """The group has running chains or recorded history, so it cannot be deleted."""


@dataclass(slots=True, frozen=True)
class SettingsValues:
    """What the owner chooses for a group (the rest of the settings row is bookkeeping)."""

    parser: str
    asset_suffix_mode: AssetSuffixMode
    timezone: str
    strategy: Strategy
    base_stake: Decimal
    max_steps: int
    multipliers: tuple[Decimal, ...]
    min_payout_pct: int


@dataclass(slots=True, frozen=True)
class GroupView:
    group: GroupRecord
    settings: GroupSettingsRecord | None


type EngineProvider = Callable[[], Engine | None]


class GroupService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        engine: EngineProvider,
        parser_names: Sequence[str],
    ) -> None:
        self._factory = session_factory
        self._clock = clock
        self._engine = engine
        self._parser_names = tuple(parser_names)

    async def list(self) -> list[GroupView]:
        async with self._factory() as session:
            repo = GroupRepository(session)
            settings = {s.group_id: s for s in await repo.list_settings()}
            return [GroupView(g, settings.get(g.id or 0)) for g in await repo.list_all()]

    async def get(self, group_id: int) -> GroupView:
        async with self._factory() as session:
            repo = GroupRepository(session)
            group = await repo.get(group_id)
            if group is None:
                raise GroupNotFoundError(f"no group {group_id}")
            return GroupView(group, await repo.get_settings(group_id))

    async def create(
        self, *, telegram_chat_id: int, title: str, enabled: bool, settings: SettingsValues
    ) -> GroupView:
        now = self._clock.now()
        try:
            async with self._factory.begin() as session:
                repo = GroupRepository(session)
                if await repo.get_by_chat_id(telegram_chat_id) is not None:
                    raise GroupExistsError(f"a group for chat {telegram_chat_id} already exists")
                group = await repo.add(
                    GroupRecord(
                        telegram_chat_id=telegram_chat_id,
                        title=title,
                        enabled=enabled,
                        created_at=now,
                        updated_at=now,
                    )
                )
                if group.id is None:
                    raise RuntimeError("the database did not assign a group id")
                record = self._settings_record(group.id, settings, now)
                await repo.save_settings(record)
        except IntegrityError as exc:  # two requests for the same chat at once
            raise GroupExistsError(f"a group for chat {telegram_chat_id} already exists") from exc
        self._tell_engine(group, record)
        return GroupView(group, record)

    async def update(
        self, group_id: int, *, title: str, enabled: bool, settings: SettingsValues
    ) -> GroupView:
        now = self._clock.now()
        async with self._factory.begin() as session:
            repo = GroupRepository(session)
            existing = await repo.get(group_id)
            if existing is None:
                raise GroupNotFoundError(f"no group {group_id}")
            group = replace(existing, title=title, enabled=enabled, updated_at=now)
            record = self._settings_record(group_id, settings, now)
            await repo.update(group)
            await repo.save_settings(record)
        self._tell_engine(group, record)
        return GroupView(group, record)

    async def delete(self, group_id: int) -> None:
        engine = self._engine()
        if engine is not None and engine.manager.active_chains(group_id):
            raise GroupInUseError("the group has running chains: end them first")
        try:
            async with self._factory.begin() as session:
                repo = GroupRepository(session)
                group = await repo.get(group_id)
                if group is None:
                    raise GroupNotFoundError(f"no group {group_id}")
                await repo.delete(group_id)
        except IntegrityError as exc:
            raise GroupInUseError(
                "the group has signals, chains or trades on record and cannot be deleted: "
                "disable it instead"
            ) from exc
        if engine is not None:
            engine.remove_group(group)

    # --- internals ---

    def _settings_record(
        self, group_id: int, values: SettingsValues, now: datetime
    ) -> GroupSettingsRecord:
        if values.parser not in self._parser_names:
            known = ", ".join(self._parser_names)
            raise InvalidGroupError(f"unknown parser {values.parser!r} (known: {known})")
        try:
            parse_timezone(values.timezone)
            return GroupSettingsRecord(
                group_id=group_id,
                parser=values.parser,
                asset_suffix_mode=values.asset_suffix_mode,
                timezone=values.timezone,
                strategy=values.strategy,
                base_stake=values.base_stake,
                max_steps=values.max_steps,
                multipliers=values.multipliers,
                min_payout_pct=values.min_payout_pct,
                updated_at=now,
            )
        except (InvalidTimezoneError, ValueError) as exc:
            raise InvalidGroupError(str(exc)) from exc

    def _tell_engine(self, group: GroupRecord, settings: GroupSettingsRecord) -> None:
        engine = self._engine()
        if engine is not None:
            engine.set_group(group, settings)
