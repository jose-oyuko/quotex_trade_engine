"""Record <-> row conversion. Record field names equal column names, so one helper covers all."""

from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

MAX_PAGE_SIZE = 1000


def to_values(record: DataclassInstance) -> dict[str, Any]:
    return {f.name: getattr(record, f.name) for f in fields(record)}


def to_record[R: DataclassInstance](record_class: type[R], row: object) -> R:
    return record_class(**{f.name: getattr(row, f.name) for f in fields(record_class)})


def page(limit: int, offset: int) -> tuple[int, int]:
    """Clamp paging arguments: lists are never unbounded."""
    return max(1, min(limit, MAX_PAGE_SIZE)), max(0, offset)
