"""Shapes shared by every endpoint: pages and the error body."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, Field

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# `Annotated` query parameters, so every list endpoint paginates the same way.
LimitParam = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Rows per page.")]
OffsetParam = Annotated[int, Query(ge=0, description="Rows to skip.")]


class Page[T](BaseModel):
    """One page of a list. `total` counts every row that matches the filters."""

    items: list[T]
    total: int = Field(ge=0)
    limit: int
    offset: int


class FieldProblem(BaseModel):
    field: str
    message: str


class ErrorDetail(BaseModel):
    """`code` is stable and meant for programs; `message` is for the owner to read."""

    code: str
    message: str
    details: list[FieldProblem] | dict[str, Any] | None = None


class ErrorBody(BaseModel):
    error: ErrorDetail
