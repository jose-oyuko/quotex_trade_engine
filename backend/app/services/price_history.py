"""Downloading past prices for backtests (decision D-84).

One download at a time, in the background. It asks the broker for pages of ticks from the newest
to the oldest, skips what the store already holds, records after every page what was downloaded
(so a cancelled or failed download keeps what it got, and a repeat asks only for the rest), and
publishes `JobChanged` so the dashboard updates live. All file work runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial

import structlog

from app.backtest.store import AssetHeld, DownloadRow, PriceStore
from app.brokers.history import PriceFeed, PriceHistory, PriceHistoryError
from app.core.clock import Clock
from app.core.errors import DomainError
from app.core.tasks import TaskSupervisor
from app.events.bus import EventBus
from app.events.types import JobChanged

log = structlog.get_logger()

PAGE = 5000  # ticks asked for per request
MAX_DAYS = 31  # per download
RETRIES = 5  # a dropped connection is opened again this many times in a row
NO_PRICES_NOTE_S = 3600  # a stretch this long without a single price is worth saying


class InvalidDownloadError(DomainError):
    """The asset or the dates of a download are not acceptable; the message says why."""


class DownloadRunningError(DomainError):
    """Only one download runs at a time."""


class DownloadNotFoundError(DomainError):
    pass


class AssetBusyError(DomainError):
    """The asset is being downloaded, so its prices cannot be deleted now."""


@dataclass(slots=True)
class _Active:
    row: DownloadRow
    task: asyncio.Task[None]
    cancel_requested: bool = False


class PriceHistoryService:
    def __init__(
        self,
        *,
        store: PriceStore,
        history: PriceHistory,
        bus: EventBus,
        tasks: TaskSupervisor,
        clock: Clock,
        pace_s: float = 0.3,
        retry_s: float = 2.0,
    ) -> None:
        self._store = store
        self._history = history
        self._bus = bus
        self._tasks = tasks
        self._clock = clock
        self._pace_s = pace_s  # Deriv allows about 220 requests a minute
        self._retry_s = retry_s  # the first wait before opening a dropped connection again
        self._active: _Active | None = None

    @property
    def store(self) -> PriceStore:
        return self._store

    async def prepare(self, *, cut_running: bool = True) -> None:
        cut = await asyncio.to_thread(
            partial(self._store.prepare, self._clock.now(), cut_running=cut_running)
        )
        if cut:
            log.warning("price_downloads_cut_by_a_stop", downloads=cut)

    async def held(self) -> list[AssetHeld]:
        return await asyncio.to_thread(self._store.held)

    async def download(self, download_id: int) -> DownloadRow | None:
        return await asyncio.to_thread(self._store.download, download_id)

    async def downloads(self, limit: int = 50) -> list[DownloadRow]:
        return await asyncio.to_thread(self._store.downloads, limit)

    @property
    def running(self) -> DownloadRow | None:
        return None if self._active is None else self._active.row

    async def start(self, asset: str, start: datetime, end: datetime) -> DownloadRow:
        """Start downloading `asset` from `start` to `end`. Raises `InvalidDownloadError`,
        `DownloadRunningError`."""
        name = asset.strip()
        if not name:
            raise InvalidDownloadError("Choose an asset.")
        now = self._clock.now()
        first, last = _epoch(start), min(_epoch(end), _epoch(now))
        if last <= first:
            raise InvalidDownloadError("The start must be before the end (and before now).")
        if last - first > MAX_DAYS * 86400:
            raise InvalidDownloadError(
                f"At most {MAX_DAYS} days per download; download longer periods in parts."
            )
        if self._active is not None:
            raise DownloadRunningError(
                f"A download of {self._active.row.asset} is running; wait for it or cancel it."
            )
        row = await asyncio.to_thread(self._store.new_download, name, first, last, now)
        task = self._tasks.spawn(self._run(row), name=f"price_download_{row.id}")
        self._active = _Active(row, task)
        log.info("price_download_started", download=row.id, asset=name, start=first, end=last)
        self._publish(row.id, "running")
        return row

    async def wait(self, timeout_s: float | None = None) -> None:
        """Until no download runs (for the terminal command and tests)."""
        active = self._active
        if active is not None:
            await asyncio.wait({active.task}, timeout=timeout_s)

    async def cancel(self, download_id: int) -> DownloadRow:
        """Stop a running download; what it stored is kept. A finished one is returned as is."""
        active = self._active
        if active is not None and active.row.id == download_id:
            active.cancel_requested = True
            active.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait({active.task}, timeout=10)
        found = await asyncio.to_thread(self._store.download, download_id)
        if found is None:
            raise DownloadNotFoundError(f"There is no download {download_id}.")
        return found

    async def forget(self, asset: str) -> None:
        if self._active is not None and self._active.row.asset == asset:
            raise AssetBusyError(f"{asset} is being downloaded; cancel the download first.")
        if not await asyncio.to_thread(self._store.forget, asset):
            raise DownloadNotFoundError(f"No prices of {asset} are stored.")
        log.info("price_history_forgotten", asset=asset)

    # ---- the download ------------------------------------------------------------------------

    async def _run(self, row: DownloadRow) -> None:
        progress = _Progress(reached=row.end + 1)
        try:
            await self._download(row, progress)
            await self._finish(row, "done", progress, error=None)
        except asyncio.CancelledError:
            active = self._active
            asked = active is not None and active.cancel_requested
            await self._finish(
                row,
                "cancelled" if asked else "failed",
                progress,
                error=None if asked else "The program stopped during the download.",
            )
            if not asked:
                raise
        except PriceHistoryError as exc:
            await self._finish(row, "failed", progress, error=str(exc))
        except Exception as exc:
            log.error("price_download_crashed", download=row.id, exc_info=True)
            await self._finish(row, "failed", progress, error=f"{type(exc).__name__}: {exc}")
        finally:
            if self._active is not None and self._active.row.id == row.id:
                self._active = None

    async def _download(self, row: DownloadRow, progress: _Progress) -> None:
        """Every missing part, newest first. A dropped connection is opened again and the
        download goes on from where it was (each page is recorded as it comes), up to
        `RETRIES` times in a row."""
        failures = 0
        while True:
            gaps = await asyncio.to_thread(self._store.missing, row.asset, row.start, row.end)
            if not gaps:
                return
            stored = progress.ticks
            try:
                async with self._history.open() as feed:
                    for gap in reversed(gaps):
                        await self._fill(row, feed, gap, progress)
                return
            except PriceHistoryError as exc:
                failures = 0 if progress.ticks > stored else failures
                if not exc.retryable or failures >= RETRIES:
                    raise
                failures += 1
                wait_s = self._retry_s * 2 ** (failures - 1)
                log.warning(
                    "price_download_retrying", download=row.id, error=str(exc), wait_s=wait_s
                )
                self._publish(row.id, "running", f"{exc} Trying again ({failures}/{RETRIES}).")
                await asyncio.sleep(wait_s)

    async def _fill(
        self, row: DownloadRow, feed: PriceFeed, gap: tuple[int, int], progress: _Progress
    ) -> None:
        start, cursor = gap
        while cursor >= start:
            page = await feed.page(row.asset, start=start, end=cursor, count=PAGE)
            kept = [(t, q) for t, q in zip(page.times, page.quotes, strict=True) if start <= t]
            kept = [(t, q) for t, q in kept if t <= cursor]
            if not kept:  # no price at all between `start` and `cursor`
                await asyncio.to_thread(self._store.cover, row.asset, start, cursor)
                if cursor - start >= NO_PRICES_NOTE_S:
                    progress.note = (
                        f"Deriv has no {row.asset} prices from {_iso(start)} to {_iso(cursor)}"
                        + (" (its history starts later)." if start == row.start else ".")
                    )
                progress.reached = min(progress.reached, start)
                break
            times = [t for t, _ in kept]
            added = await asyncio.to_thread(self._store.add, row.asset, times, [q for _, q in kept])
            await asyncio.to_thread(self._store.cover, row.asset, times[0], cursor)
            progress.ticks += added
            progress.reached = min(progress.reached, times[0])
            await asyncio.to_thread(
                self._store.update_download,
                row.id,
                ticks=progress.ticks,
                reached=progress.reached,
            )
            self._publish(
                row.id, "running", f"{progress.ticks} new prices, back to {_iso(progress.reached)}"
            )
            cursor = times[0] - 1
            if self._pace_s > 0:
                await asyncio.sleep(self._pace_s)

    async def _finish(
        self, row: DownloadRow, state: str, progress: _Progress, *, error: str | None
    ) -> None:
        await asyncio.to_thread(
            self._store.update_download,
            row.id,
            state=state,
            ticks=progress.ticks,
            reached=min(progress.reached, row.end) if state != "done" else row.start,
            note=progress.note,
            error=error,
            finished_at=self._clock.now(),
        )
        log.info(
            "price_download_ended",
            download=row.id,
            asset=row.asset,
            state=state,
            ticks=progress.ticks,
            error=error,
        )
        self._publish(row.id, state, error or progress.note)

    def _publish(self, job_id: int, state: str, detail: str | None = None) -> None:
        self._bus.publish(
            JobChanged(
                occurred_at=self._clock.now(),
                kind="download",
                job_id=job_id,
                state=state,
                detail=detail,
            )
        )


@dataclass(slots=True)
class _Progress:
    reached: int
    ticks: int = 0
    note: str | None = None


def _epoch(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp())


def _iso(epoch: int) -> str:
    return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=epoch)).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
