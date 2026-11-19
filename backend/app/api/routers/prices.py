"""Past prices for backtests (decision D-84): what is stored, and downloads started from the
dashboard. A download runs in the background; `job.changed` events say when it moves on."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Response, status

from app.api.deps import PriceHistoryDep
from app.api.schemas.prices import (
    DownloadIn,
    DownloadOut,
    DownloadsOut,
    PriceAssetOut,
    PriceRangeOut,
    PricesOut,
)
from app.backtest.store import AssetHeld, DownloadRow

router = APIRouter(prefix="/prices", tags=["prices"])


def _at(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


def download_out(row: DownloadRow) -> DownloadOut:
    span = max(row.end - row.start + 1, 1)
    done = span if row.state == "done" else row.end + 1 - (row.reached or row.end + 1)
    return DownloadOut(
        id=row.id,
        asset=row.asset,
        start=_at(row.start),
        end=_at(row.end),
        state=row.state,
        ticks=row.ticks,
        progress=round(min(max(done / span, 0.0), 1.0), 4),
        note=row.note,
        error=row.error,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


def _asset_out(held: AssetHeld) -> PriceAssetOut:
    return PriceAssetOut(
        asset=held.asset,
        ticks=held.ticks,
        first=None if held.first is None else _at(held.first),
        last=None if held.last is None else _at(held.last),
        ranges=[PriceRangeOut(start=_at(a), end=_at(b)) for a, b in held.ranges],
    )


@router.get("", response_model=PricesOut)
async def list_prices(prices: PriceHistoryDep) -> PricesOut:
    """The assets whose prices are stored, and the download running now, if any."""
    held = await prices.held()
    running = prices.running
    if running is not None:
        current = await prices.download(running.id)
        running = current or running
    return PricesOut(
        items=[_asset_out(h) for h in held],
        running=None if running is None else download_out(running),
    )


@router.get("/downloads", response_model=DownloadsOut)
async def list_downloads(prices: PriceHistoryDep) -> DownloadsOut:
    """The latest downloads, newest first."""
    return DownloadsOut(items=[download_out(row) for row in await prices.downloads()])


@router.post("/downloads", response_model=DownloadOut, status_code=status.HTTP_202_ACCEPTED)
async def start_download(body: DownloadIn, prices: PriceHistoryDep) -> DownloadOut:
    """Download the prices of an asset for a period (at most 31 days), in the background. The
    parts already stored are skipped. 409 `download_running` while another one runs."""
    return download_out(await prices.start(body.asset, body.start, body.end))


@router.post("/downloads/{download_id}/cancel", response_model=DownloadOut)
async def cancel_download(download_id: int, prices: PriceHistoryDep) -> DownloadOut:
    """Stop a running download; the prices it stored are kept."""
    return download_out(await prices.cancel(download_id))


@router.delete("/{asset}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_prices(asset: str, prices: PriceHistoryDep) -> Response:
    """Delete the stored prices of an asset."""
    await prices.forget(asset)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
