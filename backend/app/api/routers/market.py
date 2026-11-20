"""Candles and consolidation scans on the stored prices (decision D-85), for the Market page."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import MarketDep
from app.api.schemas.market import (
    BreakoutOut,
    CandleOut,
    CandlesOut,
    ConsolidationOut,
    MarketRulesIn,
    MarketStatsOut,
    PatternsOut,
    RateOut,
    ScanIn,
    ScanOut,
    SpreadOut,
    TrendOut,
)
from app.market.detector import PATTERN_DEFAULTS, Consolidation, MarketRules, Pattern, Trend
from app.market.stats import BREAK_EVEN, MarketStats, Rate, Spread
from app.services.market import InvalidMarketError

router = APIRouter(prefix="/market", tags=["market"])


def _at(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


def _rules_out(rules: MarketRules) -> MarketRulesIn:
    return MarketRulesIn(
        pattern=rules.pattern,
        candles=rules.candles,
        misses=rules.misses,
        width=rules.width,
        net_share=rules.net_share,
        breakout_candles=rules.breakout_candles,
        breakout_by=rules.breakout_by,
    )


def _rate(rate: Rate) -> RateOut:
    return RateOut(hits=rate.hits, total=rate.total, share=rate.share, low=rate.low, high=rate.high)


def _spread(s: Spread) -> SpreadOut:
    return SpreadOut(
        count=s.count, mean=s.mean, median=s.median, q1=s.q1, q3=s.q3, longest=s.longest
    )


def _consolidation(c: Consolidation, length: int) -> ConsolidationOut:
    b = c.breakout
    return ConsolidationOut(
        first=_at(c.first),
        found=_at(c.found),
        end=_at(c.end),
        candles=(c.end - c.first) // length,
        high=c.high,
        low=c.low,
        breakout=None
        if b is None
        else BreakoutOut(
            start=_at(b.start),
            known=_at(b.known),
            direction=b.direction,
            level=b.level,
            close=b.close,
        ),
        ended=c.ended or "end",
    )


def _trend(t: Trend, length: int) -> TrendOut:
    return TrendOut(
        start=_at(t.start),
        end=_at(t.end),
        stopped=_at(t.stopped),
        direction=t.direction,
        candles=(t.end - t.start) // length,
        open=t.open,
        close=t.close,
        move=t.move,
        ended=t.ended,
    )


def _stats(s: MarketStats) -> MarketStatsOut:
    return MarketStatsOut(
        candles=s.candles,
        consolidations=s.consolidations,
        breakouts=s.breakouts,
        in_consolidation=s.in_consolidation,
        trend_wait=_spread(s.trend_wait),
        any_wait=_spread(s.any_wait),
        first_with=_rate(s.first_with),
        trend_with=_rate(s.trend_with),
        break_even=BREAK_EVEN,
        deep=s.deep,
        deep_any=_rate(s.deep_any),
        deep_trend=_rate(s.deep_trend),
        deep_consolidation=_rate(s.deep_consolidation),
        described=_rate(s.described),
    )


@router.get("/patterns", response_model=PatternsOut)
async def patterns() -> PatternsOut:
    """The consolidation patterns, each with its default settings."""
    return PatternsOut(items=[_rules_out(PATTERN_DEFAULTS[p]) for p in Pattern])


@router.get("/candles", response_model=CandlesOut)
async def candles(
    market: MarketDep,
    asset: Annotated[str, Query(min_length=2, max_length=30, pattern=r"^\w+$")],
    start: datetime,
    end: datetime,
    length: Annotated[int, Query(ge=1, le=86_400)] = 60,
) -> CandlesOut:
    """The candles of an asset's stored prices, at most 5,000 per request (422
    `invalid_market` beyond). A period without stored prices simply has no candles."""
    first, last, found = await market.candles(asset, start, end, length)
    return CandlesOut(
        asset=asset,
        length=length,
        start=_at(first),
        end=_at(last),
        items=[
            CandleOut(
                start=_at(c.start),
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                ticks=c.ticks,
            )
            for c in found
        ],
    )


@router.post("/scan", response_model=ScanOut)
async def scan(body: ScanIn, market: MarketDep) -> ScanOut:
    """Every consolidation, breakout and trend in a period (at most 31 days), with the
    statistics. 422 `invalid_market` without stored prices or with settings that do not fit."""
    r = body.rules
    try:
        rules = MarketRules(
            pattern=r.pattern,
            candles=r.candles,
            misses=r.misses,
            width=r.width,
            net_share=r.net_share,
            breakout_candles=r.breakout_candles,
            breakout_by=r.breakout_by,
        )
    except ValueError as exc:
        raise InvalidMarketError(str(exc)) from exc
    found = await market.scan(body.asset, body.start, body.end, body.length, rules, body.deep)
    return ScanOut(
        asset=found.asset,
        length=found.length,
        start=_at(found.start),
        end=_at(found.end),
        rules=_rules_out(rules),
        consolidations=[_consolidation(c, found.length) for c in found.found.consolidations],
        trends=[_trend(t, found.length) for t in found.found.trends],
        stats=_stats(found.stats),
    )
