"""Download Deriv's past prices for backtests (decision D-84), from the terminal.

    npm run history:download -- --asset 1HZ75V --days 1
    npm run history:download -- --asset R_75 --from 2026-11-01 --to 2026-11-08

Uses Deriv's public price service: no token, no account, nothing is traded. The prices go to
`data/history.db`, the same file the dashboard's Backtest page uses; parts already stored are
skipped. At most 31 days per run. Ctrl+C stops it and keeps what was stored.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from app.backtest.store import PriceStore
from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.engine.factory import build_price_history
from app.events.bus import EventBus
from app.events.types import JobChanged
from app.services.price_history import InvalidDownloadError, PriceHistoryService


def _day(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


async def run(settings: Settings, asset: str, start: datetime, end: datetime) -> int:
    tasks, bus, clock = TaskSupervisor(), EventBus(), SystemClock()
    service = PriceHistoryService(
        store=PriceStore(settings.history_path),
        history=build_price_history(settings, tasks),
        bus=bus,
        tasks=tasks,
        clock=clock,
    )
    await service.prepare(cut_running=False)  # the dashboard may be downloading too
    events = bus.subscribe(JobChanged, name="history_cli")
    try:
        row = await service.start(asset, start, end)
    except InvalidDownloadError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    print(f"Downloading {asset} from {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC ...")
    try:
        while True:
            event = await events.get()
            assert isinstance(event, JobChanged)  # noqa: S101 - subscribed to it only
            if event.detail:
                print(f"  {event.state}: {event.detail}")
            if event.state != "running":
                break
    except (KeyboardInterrupt, asyncio.CancelledError):
        await service.cancel(row.id)
    finally:
        await service.wait(30)
        await tasks.shutdown()
    final = await service.download(row.id)
    if final is None:
        return 1
    print(f"{final.state}: {final.ticks} new prices stored in {settings.history_path}")
    if final.error:
        print(f"error: {final.error}")
    return 0 if final.state == "done" else 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--asset", required=True, help="R_75, 1HZ75V, EURUSD ...")
    parser.add_argument("--days", type=float, default=1.0, help="the last N days (default 1)")
    parser.add_argument("--from", dest="start", type=_day, help="YYYY-MM-DD (UTC)")
    parser.add_argument("--to", dest="end", type=_day, help="YYYY-MM-DD (UTC), default now")
    args = parser.parse_args(argv)
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.stderr.write(f"Invalid configuration:\n{exc}\n")
        return 2
    end = args.end or datetime.now(UTC)
    start = args.start or end - timedelta(days=args.days)
    return asyncio.run(run(settings, args.asset, start, end))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
