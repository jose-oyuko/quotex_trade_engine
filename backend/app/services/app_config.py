"""The few settings the owner changes from the dashboard instead of `backend/.env` (decision D-58).

A value lives in the database (`app_settings`, key `config.<name>`) and wins over `.env`, which wins
over the built-in default. The application reads them once, when it starts; saving one therefore
takes effect at the next start (the engine can be restarted on its own from Phase 12).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.core.config import Settings, normalise_quotex_host
from app.core.errors import DomainError
from app.db.repositories import AppSettingsRepository

log = structlog.get_logger()

PREFIX = "config."


class InvalidSettingError(DomainError):
    """The setting does not exist or the value is not acceptable (the message says why)."""


def _choice(*options: str, label: str) -> Callable[[str], str]:
    def check(value: str) -> str:
        cleaned = value.strip().upper() if options[0].isupper() else value.strip()
        if cleaned not in options:
            raise InvalidSettingError(f"{label} must be one of: {', '.join(options)}.")
        return cleaned

    return check


def _host(value: str) -> str:
    try:
        return normalise_quotex_host(value)
    except ValueError as exc:
        raise InvalidSettingError(str(exc).replace("QUOTEX_HOST", "The Quotex address")) from exc


@dataclass(slots=True, frozen=True)
class ConfigField:
    key: str
    label: str
    help: str
    kind: Literal["choice", "text"]
    choices: tuple[str, ...]
    check: Callable[[str], str]


FIELDS: tuple[ConfigField, ...] = (
    ConfigField(
        "log_level",
        "Log detail",
        "How much the application writes to its log. INFO is right for daily use; DEBUG is for "
        "finding a problem.",
        "choice",
        ("DEBUG", "INFO", "WARNING", "ERROR"),
        _choice("DEBUG", "INFO", "WARNING", "ERROR", label="Log detail"),
    ),
    ConfigField(
        "quotex_host",
        "Quotex address",
        "The domain Quotex is reached at. It changes now and then: type only the domain, such as "
        "quotex.com.",
        "text",
        (),
        _host,
    ),
    ConfigField(
        "quotex_time_mode",
        "Trade expiry mode",
        "TIME: a trade ends at the next clock-aligned time. TIMER: it ends after a countdown of "
        "the signal's length.",
        "choice",
        ("TIME", "TIMER"),
        _choice("TIME", "TIMER", label="Trade expiry mode"),
    ),
)
FIELD_BY_KEY = {f.key: f for f in FIELDS}


@dataclass(slots=True, frozen=True)
class ConfigItem:
    field: ConfigField
    value: str  # what the application uses (at its next start)
    default_value: str  # what it would use without the stored value
    source: Literal["database", "environment", "default"]


class ConfigService:
    def __init__(
        self, base: Settings, session_factory: async_sessionmaker[AsyncSession], clock: Clock
    ) -> None:
        self._base = base  # the settings as `.env` and the defaults give them
        self._sessions = session_factory
        self._clock = clock

    async def _stored(self) -> dict[str, str]:
        """The stored values that are still acceptable. A damaged one is ignored (and logged): the
        application must start, using `.env`'s value, rather than refuse because of a typo."""
        async with self._sessions() as session:
            rows = await AppSettingsRepository(session).all()
        stored: dict[str, str] = {}
        for row in rows:
            if not row.key.startswith(PREFIX):
                continue
            field = FIELD_BY_KEY.get(row.key.removeprefix(PREFIX))
            if field is None or not isinstance(row.value, str):
                continue
            try:
                stored[field.key] = field.check(row.value)
            except InvalidSettingError:
                log.warning("stored_setting_ignored", key=field.key)
        return stored

    async def effective(self) -> Settings:
        """The settings the application runs with: `.env` and defaults, then the stored values."""
        stored = await self._stored()
        return self._base.model_copy(update=stored) if stored else self._base

    async def items(self) -> list[ConfigItem]:
        stored = await self._stored()
        items: list[ConfigItem] = []
        for field in FIELDS:
            default = str(getattr(self._base, field.key))
            if field.key in stored:
                source: Literal["database", "environment", "default"] = "database"
            elif field.key in self._base.model_fields_set:
                source = "environment"
            else:
                source = "default"
            items.append(ConfigItem(field, stored.get(field.key, default), default, source))
        return items

    async def update(self, changes: Mapping[str, str | None]) -> None:
        """Save new values; `None` removes the stored value (back to `.env` / the default). Checks
        everything first, so a bad value changes nothing."""
        checked: dict[str, str | None] = {}
        for key, value in changes.items():
            field = FIELD_BY_KEY.get(key)
            if field is None:
                raise InvalidSettingError(f"There is no setting called {key!r}.")
            checked[key] = None if value is None else field.check(value)
        now = self._clock.now()
        async with self._sessions() as session, session.begin():
            repo = AppSettingsRepository(session)
            for key, value in checked.items():
                if value is None:
                    await repo.delete(PREFIX + key)
                else:
                    await repo.set(PREFIX + key, value, now=now)
        log.info("settings_changed", keys=sorted(checked))
