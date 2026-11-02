"""Small SQL building blocks that differ between databases, so the report queries stay portable
(decision D-3): the part of a stored UTC time that falls on the owner's clock.

SQLite has `strftime`; PostgreSQL has `EXTRACT`/`to_char`. The offset is an integer we validate
ourselves, so it is written into the statement as a number (never as text from a request).
The PostgreSQL branch is written to the same contract but has not been run: there is no
PostgreSQL in this project yet (it is a "later" item).
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import Integer, String
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement
from sqlalchemy.sql.visitors import InternalTraversal

type Part = Literal["hour", "weekday", "day"]


class LocalPart(FunctionElement[Any]):
    """`hour` (0-23), `weekday` (Monday=0 ... Sunday=6) or `day` ('YYYY-MM-DD') of `column` shifted
    by `offset_minutes`."""

    inherit_cache = True
    name = "local_part"
    # SQLAlchemy caches the compiled form of a statement by its structure. `part` and the offset
    # change the SQL we write, so they must be part of that key: without them the "hour" statement
    # and the "weekday" statement look identical and one is served the other's SQL.
    _traverse_internals = [  # noqa: RUF012  (SQLAlchemy reads it from the class)
        *FunctionElement._traverse_internals,
        ("part", InternalTraversal.dp_string),
        ("offset_minutes", InternalTraversal.dp_plain_obj),
    ]

    def __init__(self, column: Any, part: Part, offset_minutes: int) -> None:
        super().__init__(column)
        self.column = column
        self.part = part
        self.offset_minutes = int(offset_minutes)
        self.type = String() if part == "day" else Integer()


@compiles(LocalPart, "sqlite")
def _sqlite_local_part(element: LocalPart, compiler: Any, **kw: Any) -> str:
    column = compiler.process(element.column, **kw)
    shift = f"'{element.offset_minutes:+d} minutes'"
    if element.part == "day":
        return f"strftime('%Y-%m-%d', {column}, {shift})"
    if element.part == "hour":
        return f"CAST(strftime('%H', {column}, {shift}) AS INTEGER)"
    # strftime('%w') counts Sunday as 0; Monday=0 is what a human expects of a week
    return f"((CAST(strftime('%w', {column}, {shift}) AS INTEGER) + 6) % 7)"


@compiles(LocalPart)
def _default_local_part(element: LocalPart, compiler: Any, **kw: Any) -> str:
    column = compiler.process(element.column, **kw)
    shifted = f"({column} + make_interval(mins => {element.offset_minutes}))"
    if element.part == "day":
        return f"to_char({shifted}, 'YYYY-MM-DD')"
    if element.part == "hour":
        return f"CAST(EXTRACT(HOUR FROM {shifted}) AS INTEGER)"
    return f"(CAST(EXTRACT(ISODOW FROM {shifted}) AS INTEGER) - 1)"
