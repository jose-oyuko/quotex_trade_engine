"""Candles, consolidations, breakouts and trends on the stored prices (decision D-85)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.market.detector import MAX_CANDLES, BreakBy, Pattern

Direction = Literal["up", "down"]


class CandleOut(BaseModel):
    start: datetime
    open: float
    high: float
    low: float
    close: float
    ticks: int = Field(description="Prices inside the candle.")


class CandlesOut(BaseModel):
    asset: str
    length: int = Field(description="Seconds per candle.")
    start: datetime
    end: datetime
    items: list[CandleOut] = Field(description="Oldest first; a period without prices has none.")


class MarketRulesIn(BaseModel):
    """What counts as a consolidation and a breakout (docs/DOMAIN.md, section 9)."""

    model_config = ConfigDict(extra="forbid")

    pattern: Pattern = Pattern.ALTERNATING
    candles: int = Field(default=5, ge=2, le=MAX_CANDLES, description="Candles in the pattern.")
    misses: int = Field(
        default=1, ge=0, le=MAX_CANDLES - 2, description="`mixed`: candles that may not alternate."
    )
    width: float = Field(
        default=2.0, gt=0, le=20, description="`tight`: the range, in average candles."
    )
    net_share: float = Field(
        default=0.2, gt=0, lt=1, description="`choppy`: the largest net move, as a share."
    )
    breakout_candles: int = Field(default=2, ge=1, le=10)
    breakout_by: BreakBy = BreakBy.CLOSE


class PatternsOut(BaseModel):
    items: list[MarketRulesIn] = Field(description="Each pattern with its default settings.")


class ScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str = Field(min_length=2, max_length=30, pattern=r"^\w+$")
    start: datetime
    end: datetime = Field(description="At most 31 days after `start`.")
    length: int = Field(default=60, ge=1, le=86_400, description="Seconds per candle.")
    rules: MarketRulesIn = Field(default_factory=MarketRulesIn)
    deep: int = Field(default=6, ge=2, le=9, description="Trades lost in a row that count as deep.")


class BreakoutOut(BaseModel):
    start: datetime = Field(description="The first breakout candle.")
    known: datetime = Field(description="When the breakout was known: the last one's end.")
    direction: Direction
    level: float = Field(description="The range's high (up) or low (down) that was broken.")
    close: float


class ConsolidationOut(BaseModel):
    first: datetime = Field(description="Its first candle.")
    found: datetime = Field(description="When the pattern was complete.")
    end: datetime = Field(description="The end of its last candle.")
    candles: int
    high: float
    low: float
    breakout: BreakoutOut | None
    ended: Literal["breakout", "gap", "end"]


class TrendOut(BaseModel):
    start: datetime = Field(description="The candle after the breakout.")
    end: datetime = Field(description="Where the next consolidation starts (or a gap, the end).")
    stopped: datetime = Field(description="When its end was known.")
    direction: Direction
    candles: int
    open: float = Field(description="The breakout's close.")
    close: float
    move: float = Field(description="How far the price went the breakout's way.")
    ended: Literal["consolidation", "gap", "end"]


class SpreadOut(BaseModel):
    count: int
    mean: float
    median: float
    q1: float
    q3: float
    longest: int


class RateOut(BaseModel):
    hits: int
    total: int
    share: float
    low: float = Field(description="The 95% range: below this is unlikely.")
    high: float


class MarketStatsOut(BaseModel):
    candles: int
    consolidations: int
    breakouts: int
    in_consolidation: float = Field(description="Share of the candles inside a consolidation.")
    trend_wait: SpreadOut = Field(
        description="Candles from a breakout until the next consolidation was found."
    )
    any_wait: SpreadOut = Field(description="The same, from any candle: the comparison.")
    first_with: RateOut = Field(description="The candle after a breakout went its way.")
    trend_with: RateOut = Field(description="The trends' candles that went the breakout's way.")
    break_even: float = Field(description="The share of wins that pays for the losses at 88%.")
    deep: int
    deep_any: RateOut = Field(description="Flip pairs started at any candle that went deep.")
    deep_trend: RateOut = Field(description="... started while trending.")
    deep_consolidation: RateOut = Field(description="... started in a known consolidation.")
    described: RateOut = Field(
        description="Candles of the stretches that took pairs deep that lie in a consolidation."
    )


class ScanOut(BaseModel):
    asset: str
    length: int
    start: datetime
    end: datetime
    rules: MarketRulesIn
    consolidations: list[ConsolidationOut]
    trends: list[TrendOut]
    stats: MarketStatsOut
