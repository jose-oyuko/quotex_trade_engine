"""Identifiers are generated in memory so the hot path never waits for the database."""

from __future__ import annotations

from uuid import UUID, uuid4


def new_id() -> UUID:
    return uuid4()
