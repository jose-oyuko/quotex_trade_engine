"""The report SQL helpers: what they write, and that the statement cache tells them apart."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import Dialect, select
from sqlalchemy.dialects import postgresql, sqlite

from app.db.models import Trade
from app.reports.sql import LocalPart

SQLITE = sqlite.dialect()


def sql(part: str, offset: int = 0, dialect: Dialect = SQLITE) -> str:
    statement = select(LocalPart(Trade.settled_at, part, offset))  # type: ignore[arg-type]
    return str(statement.compile(dialect=dialect))


def test_hour_weekday_and_day_are_different_statements_for_the_statement_cache() -> None:
    """The bug this guards against: one statement served another's cached SQL."""
    keys = {
        select(LocalPart(Trade.settled_at, part, offset))._generate_cache_key().key  # type: ignore[arg-type]
        for part in ("hour", "weekday", "day")
        for offset in (0, -180, 180)
    }
    assert len(keys) == 9
    first = select(LocalPart(Trade.settled_at, "hour", 0))
    again = select(LocalPart(Trade.settled_at, "hour", 0))
    assert (
        first._generate_cache_key().key == again._generate_cache_key().key
    )  # equal ones still share


@pytest.mark.parametrize(
    ("stored", "offset", "hour", "weekday", "day"),
    [
        ("2026-11-02 10:30:00.123456", 0, 10, 0, "2026-11-02"),  # Monday
        ("2026-11-01 23:30:00.000000", 0, 23, 6, "2026-11-01"),  # Sunday is 6, not 0
        ("2026-11-01 23:30:00.000000", 60, 0, 0, "2026-11-02"),  # +1 h crosses into Monday
        ("2026-11-02 00:10:00.000000", -180, 21, 6, "2026-11-01"),  # UTC-3 crosses back
        ("2026-12-31 22:00:00.000000", 180, 1, 4, "2027-01-01"),  # across the new year, a Friday
    ],
)
def test_the_sqlite_expressions_give_the_owners_hour_weekday_and_day(
    stored: str, offset: int, hour: int, weekday: int, day: str
) -> None:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE trades (settled_at TEXT)")
    db.execute("INSERT INTO trades VALUES (?)", (stored,))
    for part, expected in (("hour", hour), ("weekday", weekday), ("day", day)):
        text = sql(part, offset).replace("SELECT ", "SELECT ", 1)
        assert db.execute(text).fetchone()[0] == expected, (stored, offset, part)


def test_the_postgres_branch_uses_the_standard_functions() -> None:
    """Written to the same contract; not run against a PostgreSQL (there is none yet)."""
    pg = postgresql.dialect()
    assert "EXTRACT(HOUR FROM" in sql("hour", 60, pg)
    assert "ISODOW" in sql("weekday", 0, pg) and "- 1" in sql("weekday", 0, pg)
    assert "to_char(" in sql("day", -180, pg) and "make_interval(mins => -180)" in sql(
        "day", -180, pg
    )


def test_the_offset_is_always_a_whole_number() -> None:
    assert "'+0 minutes'" in sql("hour", 0)
    assert "'-30 minutes'" in sql("hour", -30)
    with pytest.raises(ValueError):
        LocalPart(Trade.settled_at, "hour", "1; DROP TABLE trades")  # type: ignore[arg-type]
