"""Column types that keep the schema portable and the stored data unambiguous."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes. SQLite drops the zone, so we always store UTC and re-attach
    it on the way out; naive datetimes are refused rather than guessed."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime refused: use a timezone-aware datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Money(TypeDecorator[Decimal]):
    """Money as integer minor units (cents) in the database, `Decimal` in Python (decision D-22).
    Floats are refused, and so is anything with more than two decimals: rounding a stake is the
    strategy's job and must never happen silently at the storage layer."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> int | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError(f"Money needs a Decimal, got {type(value).__name__}")
        minor = value.scaleb(2)
        if minor != minor.to_integral_value():
            raise ValueError(f"{value} has more than 2 decimal places")
        return int(minor)

    def process_result_value(self, value: int | None, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value).scaleb(-2)


class DecimalList(TypeDecorator[tuple[Decimal, ...]]):
    """A tuple of Decimals stored as a JSON list of strings (exact, no float round-trip)."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: tuple[Decimal, ...] | None, dialect: Dialect) -> Any:
        return None if value is None else [str(d) for d in value]

    def process_result_value(self, value: Any, dialect: Dialect) -> tuple[Decimal, ...] | None:
        return None if value is None else tuple(Decimal(s) for s in value)
