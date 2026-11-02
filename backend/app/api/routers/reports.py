"""Reports: is this really working? (definitions: `app/reports/models.py`, decision D-47)

All of them are read-only, take the same filters, and report demo and real separately (the account
is always one or the other, default demo). The numbers come from SQL aggregations; the CSV files
open in Excel (`app/reports/csvout.py`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse

from app.api.deps import SessionDep
from app.api.errors import ApiError
from app.api.schemas.reports import (
    BreakdownOut,
    DepthOut,
    EquityOut,
    SummaryOut,
    breakdown_out,
    depth_out,
    equity_out,
    summary_out,
)
from app.domain.enums import AccountType, Strategy
from app.reports import queries
from app.reports.csvout import Delimiter, breakdown_csv, trades_csv
from app.reports.models import BreakdownKind, ReportFilter

router = APIRouter(prefix="/reports", tags=["reports"])


def _aware(value: datetime | None, name: str) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ApiError(
            422,
            "invalid_range",
            f"`{name}` must include a time zone, like 2026-11-02T00:00:00Z",
        )
    return value


def report_filter(
    account_type: Annotated[AccountType, Query(description="Demo and real are never mixed.")] = (
        AccountType.DEMO
    ),
    from_: Annotated[
        datetime | None,
        Query(alias="from", description="Start of the range (inclusive), ISO time with a zone."),
    ] = None,
    to: Annotated[
        datetime | None, Query(description="End of the range (exclusive), ISO time with a zone.")
    ] = None,
    group_id: int | None = None,
    strategy: Strategy | None = None,
    asset: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    utc_offset_minutes: Annotated[
        int,
        Query(
            ge=-840,
            le=840,
            description="Your clock for hour of day, weekday and days: minutes from UTC "
            "(UTC-3 is -180). A fixed offset: daylight saving is not followed.",
        ),
    ] = 0,
) -> ReportFilter:
    since, until = _aware(from_, "from"), _aware(to, "to")
    try:
        return ReportFilter(
            account_type=account_type,
            since=since.astimezone(UTC) if since else None,
            until=until.astimezone(UTC) if until else None,
            group_id=group_id,
            strategy=strategy,
            asset=asset,
            utc_offset_minutes=utc_offset_minutes,
        )
    except ValueError as exc:
        raise ApiError(422, "invalid_range", str(exc)) from exc


FilterDep = Annotated[ReportFilter, Depends(report_filter)]


@router.get("/summary", response_model=SummaryOut)
async def get_summary(flt: FilterDep, session: SessionDep) -> SummaryOut:
    """Profit, win rate, drawdown, streaks and how the win rate compares with break-even."""
    return summary_out(flt, await queries.summary(session, flt))


@router.get("/breakdown", response_model=BreakdownOut)
async def get_breakdown(flt: FilterDep, session: SessionDep, by: BreakdownKind) -> BreakdownOut:
    """The same figures split by group, asset, strategy, hour of day or weekday."""
    return breakdown_out(flt, by, await queries.breakdown(session, flt, by))


@router.get("/equity", response_model=EquityOut)
async def get_equity(flt: FilterDep, session: SessionDep) -> EquityOut:
    """The result of each day with trades and the running total, for the profit curve."""
    return equity_out(flt, await queries.equity(session, flt))


@router.get("/depth", response_model=DepthOut)
async def get_depth(flt: FilterDep, session: SessionDep) -> DepthOut:
    """How far chains go: how often each step is reached, and what it costs."""
    return depth_out(flt, await queries.depth(session, flt))


# --- CSV downloads ---


def _download(name: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{name}"'}


def _filename(kind: str, flt: ReportFilter) -> str:
    return f"quotex-{kind}-{flt.account_type.value}-{datetime.now(UTC):%Y-%m-%d}.csv"


@router.get(
    "/export/trades.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "One row per trade."}},
)
async def export_trades_csv(
    flt: FilterDep,
    request: Request,
    delimiter: Annotated[Delimiter, Query(description="`semicolon` for Excel in many locales.")] = (
        Delimiter.COMMA
    ),
) -> StreamingResponse:
    """Every trade in the range, whatever its status (the range here is when it was created), as a
    UTF-8 CSV with a byte-order mark. Streamed, so a long history does not sit in memory."""
    factory = request.app.state.session_factory
    if factory is None:
        raise ApiError(503, "unavailable", "The application is still starting.")

    async def rows() -> AsyncIterator[bytes]:
        async with factory() as session:  # its own session: the stream outlives the request handler
            async for chunk in trades_csv(queries.export_trades(session, flt), delimiter):
                yield chunk

    return StreamingResponse(
        rows(),
        media_type="text/csv; charset=utf-8",
        headers=_download(_filename("trades", flt)),
    )


@router.get(
    "/export/breakdown.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "One row per group of trades."}},
)
async def export_breakdown_csv(
    flt: FilterDep,
    session: SessionDep,
    by: BreakdownKind,
    delimiter: Delimiter = Delimiter.COMMA,
) -> Response:
    """A breakdown as a CSV file."""
    rows = await queries.breakdown(session, flt, by)
    return Response(
        breakdown_csv(rows, delimiter),
        media_type="text/csv; charset=utf-8",
        headers=_download(_filename(f"by-{by.value}", flt)),
    )
