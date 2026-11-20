"""Candles and consolidation scans on the stored prices (decision D-85), for the Market page.

The prices are the ones downloaded for backtests (`data/history.db`). Loading them and scanning
run in a worker thread: a month of 1-second prices is millions of rows, and the event loop never
waits on them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from app.backtest.store import PriceStore
from app.core.errors import DomainError
from app.market.candles import Candle, candles_from_ticks
from app.market.detector import Found, MarketRules, scan
from app.market.stats import DEEP, MarketStats, market_stats

MAX_DAYS = 31  # per scan
MAX_CHART_CANDLES = 5_000  # per request for the chart
MAX_SCAN_CANDLES = 200_000
MAX_LENGTH_S = 86_400


class InvalidMarketError(DomainError):
    """The period, the candle length or the asset cannot be read."""


@dataclass(frozen=True, slots=True)
class MarketScan:
    asset: str
    length: int
    start: int
    end: int
    rules: MarketRules
    candles: int
    found: Found
    stats: MarketStats


def span(start: datetime, end: datetime, length: int, limit: int) -> tuple[int, int]:
    """The period as whole candles (epoch seconds, end excluded), checked."""
    if not 1 <= length <= MAX_LENGTH_S:
        raise InvalidMarketError(f"A candle lasts 1 second to 1 day, not {length} s.")
    if start.tzinfo is None or end.tzinfo is None:
        raise InvalidMarketError("Give the times with their time zone (e.g. Z for UTC).")
    first = int(start.timestamp()) // length * length
    last = -(-int(end.timestamp()) // length) * length
    if last <= first:
        raise InvalidMarketError("The end must come after the start.")
    if last - first > MAX_DAYS * 86_400:
        raise InvalidMarketError(f"At most {MAX_DAYS} days at a time.")
    if (last - first) // length > limit:
        raise InvalidMarketError(
            f"That is more than {limit:,} candles: choose a shorter period or longer candles."
        )
    return first, last


def load_candles(store: PriceStore, asset: str, start: int, end: int, length: int) -> list[Candle]:
    """The candles of the stored prices from `start` (included) to `end` (excluded)."""
    times, quotes = store.load(asset, start, end - 1)
    return candles_from_ticks(times, quotes, length)


def scan_stored(
    store: PriceStore,
    asset: str,
    start: int,
    end: int,
    length: int,
    rules: MarketRules,
    deep: int = DEEP,
) -> MarketScan:
    candles = load_candles(store, asset, start, end, length)
    if not candles:
        raise InvalidMarketError(
            f"No prices of {asset} are stored from {_day(start)} to {_day(end)}: "
            "download them on the Backtest page first."
        )
    found = scan(candles, rules, length)
    return MarketScan(
        asset=asset,
        length=length,
        start=start,
        end=end,
        rules=rules,
        candles=len(candles),
        found=found,
        stats=market_stats(candles, found, rules, deep=deep),
    )


def _day(epoch: int) -> str:
    return f"{datetime.fromtimestamp(epoch, tz=UTC):%Y-%m-%d %H:%M} UTC"


class MarketService:
    def __init__(self, store: PriceStore) -> None:
        self._store = store

    async def candles(
        self, asset: str, start: datetime, end: datetime, length: int
    ) -> tuple[int, int, list[Candle]]:
        """The candles for the chart (at most `MAX_CHART_CANDLES`); none where nothing is stored."""
        first, last = span(start, end, length, MAX_CHART_CANDLES)
        found = await asyncio.to_thread(load_candles, self._store, asset, first, last, length)
        return first, last, found

    async def scan(
        self,
        asset: str,
        start: datetime,
        end: datetime,
        length: int,
        rules: MarketRules,
        deep: int = DEEP,
    ) -> MarketScan:
        first, last = span(start, end, length, MAX_SCAN_CANDLES)
        return await asyncio.to_thread(
            scan_stored, self._store, asset, first, last, length, rules, deep
        )
