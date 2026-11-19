"""Past prices for backtests (decision D-84): what is stored, and the downloads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DownloadState = Literal["running", "done", "failed", "cancelled"]


class PriceRangeOut(BaseModel):
    start: datetime
    end: datetime


class PriceAssetOut(BaseModel):
    asset: str
    ticks: int = Field(description="Prices stored.")
    first: datetime | None = Field(description="The oldest stored price.")
    last: datetime | None
    ranges: list[PriceRangeOut] = Field(description="The periods downloaded, oldest first.")


class DownloadOut(BaseModel):
    id: int
    asset: str
    start: datetime
    end: datetime
    state: DownloadState
    ticks: int = Field(description="New prices stored by this download.")
    progress: float = Field(ge=0, le=1, description="Share of the period downloaded so far.")
    note: str | None = Field(description="E.g. where Deriv's history starts.")
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class PricesOut(BaseModel):
    items: list[PriceAssetOut]
    running: DownloadOut | None


class DownloadsOut(BaseModel):
    items: list[DownloadOut]


class DownloadIn(BaseModel):
    asset: str = Field(min_length=1, max_length=30, pattern=r"^\w+$")
    start: datetime
    end: datetime
