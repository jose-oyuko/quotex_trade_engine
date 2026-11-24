"""Running backtests (decision D-84): one at a time, in a worker thread, with live progress.

The replay itself (`app/backtest/replay.py`) is pure; this service loads the stored prices, runs it
off the event loop, keeps the result in the price file (`data/history.db`) and publishes
`JobChanged` so the dashboard updates. A backtest never trades and never touches a broker.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time as monotonic
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from functools import partial
from typing import Any

import structlog

from app.backtest.replay import (
    MAX_RUNS,
    WARMUP_CANDLES,
    BacktestResult,
    BacktestSetup,
    Cancelled,
    OpenRule,
    Prices,
    Run,
    StrategySetup,
    Totals,
    replay,
)
from app.backtest.store import BacktestRow, BacktestStore, ChainRow, subtract
from app.core.clock import Clock
from app.core.errors import DomainError
from app.core.tasks import TaskSupervisor
from app.domain.enums import SessionMode, Strategy
from app.events.bus import EventBus
from app.events.types import JobChanged
from app.market.detector import BreakBy, MarketRules, Pattern

log = structlog.get_logger()

MAX_DAYS = 92  # per backtest
MAX_PAIRS_SHOWN = 20_000  # pairs a run shows on the Market page
PROGRESS_EVERY_S = 1.0


class InvalidBacktestError(DomainError):
    """The setup cannot be replayed (no window in those days, no prices stored ...)."""


class BacktestRunningError(DomainError):
    """Only one backtest runs at a time."""


class BacktestNotFoundError(DomainError):
    pass


@dataclass(slots=True, frozen=True)
class PairShown:
    at: int  # when its first trades started
    profit: Decimal
    lost: bool  # a leg lost every step


@dataclass(slots=True)
class _Active:
    row: BacktestRow
    task: asyncio.Task[None]
    cancel: threading.Event


class BacktestService:
    def __init__(
        self,
        *,
        store: BacktestStore,
        bus: EventBus,
        tasks: TaskSupervisor,
        clock: Clock,
    ) -> None:
        self._store = store
        self._bus = bus
        self._tasks = tasks
        self._clock = clock
        self._active: _Active | None = None

    @property
    def running(self) -> BacktestRow | None:
        return None if self._active is None else self._active.row

    async def recent(self, limit: int = 50) -> list[BacktestRow]:
        return await asyncio.to_thread(self._store.backtests, limit)

    async def get(self, backtest_id: int) -> BacktestRow:
        found = await asyncio.to_thread(self._store.backtest, backtest_id)
        if found is None:
            raise BacktestNotFoundError(f"There is no backtest {backtest_id}.")
        return found

    async def chains(
        self,
        backtest_id: int,
        *,
        strategy: int | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ChainRow], int]:
        await self.get(backtest_id)
        return await asyncio.to_thread(
            partial(
                self._store.chains,
                backtest_id,
                strategy=strategy,
                status=status,
                limit=limit,
                offset=offset,
            )
        )

    async def pairs(self, backtest_id: int, run: int) -> tuple[list[PairShown], int]:
        """Where a run opened its pairs, oldest first, and how many there are."""
        await self.get(backtest_id)
        rows = await asyncio.to_thread(self._store.chain_outcomes, backtest_id, run)
        found: dict[tuple[str, int], PairShown] = {}
        for day, pair_no, started, status, profit in rows:
            key = (day, pair_no)
            seen = found.get(key)
            lost = status == "exhausted"
            found[key] = (
                PairShown(started, Decimal(profit), lost)
                if seen is None
                else PairShown(
                    min(seen.at, started), seen.profit + Decimal(profit), seen.lost or lost
                )
            )
        pairs = sorted(found.values(), key=lambda p: p.at)
        return pairs[:MAX_PAIRS_SHOWN], len(pairs)

    async def start(self, setup: BacktestSetup, name: str | None = None) -> BacktestRow:
        """Check the setup and replay it in the background. Raises `InvalidBacktestError`,
        `BacktestRunningError`."""
        for first_day, last_day in setup.periods():
            if (last_day - first_day).days + 1 > MAX_DAYS:
                raise InvalidBacktestError(f"At most {MAX_DAYS} days per period.")
        if len(setup.runs()) > MAX_RUNS:
            raise InvalidBacktestError(
                f"At most {MAX_RUNS} runs (strategies x ways of opening x periods)."
            )
        for period in range(1, len(setup.periods()) + 1):
            if not setup.windows(period):
                which = "the chosen days" if period == 1 else "the days of the second period"
                raise InvalidBacktestError(f"No session window falls on {which}.")
        windows = setup.all_windows()
        if self._active is not None:
            raise BacktestRunningError("A backtest is running; wait for it or cancel it.")
        first, last = int(windows[0].start.timestamp()), int(windows[-1].end.timestamp())
        covered = await asyncio.to_thread(self._store.coverage, setup.asset)
        if not covered or subtract((first, last), covered) == [(first, last)]:
            raise InvalidBacktestError(
                f"No prices of {setup.asset} are stored for these days: download them first."
            )
        label = name or _default_name(setup)
        row = await asyncio.to_thread(
            self._store.new_backtest, label, json.dumps(setup_to_json(setup)), self._clock.now()
        )
        cancel = threading.Event()
        task = self._tasks.spawn(self._run(row, setup, cancel), name=f"backtest_{row.id}")
        self._active = _Active(row, task, cancel)
        log.info("backtest_started", backtest=row.id, asset=setup.asset, windows=len(windows))
        self._publish(row.id, "running")
        return row

    async def wait(self, timeout_s: float | None = None) -> None:
        active = self._active
        if active is not None:
            await asyncio.wait({active.task}, timeout=timeout_s)

    async def cancel(self, backtest_id: int) -> BacktestRow:
        active = self._active
        if active is not None and active.row.id == backtest_id:
            active.cancel.set()
            await asyncio.wait({active.task}, timeout=30)
        return await self.get(backtest_id)

    async def delete(self, backtest_id: int) -> None:
        if self._active is not None and self._active.row.id == backtest_id:
            raise BacktestRunningError("This backtest is running; cancel it first.")
        if not await asyncio.to_thread(self._store.delete_backtest, backtest_id):
            raise BacktestNotFoundError(f"There is no backtest {backtest_id}.")

    # ---- the run -------------------------------------------------------------------------------

    async def _run(self, row: BacktestRow, setup: BacktestSetup, cancel: threading.Event) -> None:
        loop = asyncio.get_running_loop()
        last = [0.0]

        def progress(share: float) -> None:  # called in the worker thread
            now = monotonic.monotonic()
            if now - last[0] >= PROGRESS_EVERY_S:
                last[0] = now
                loop.call_soon_threadsafe(self._progressed, row.id, share)

        started = monotonic.perf_counter()
        try:
            prices = await asyncio.to_thread(self._prices, setup)
            result = await asyncio.to_thread(
                partial(replay, prices, setup, progress=progress, cancel=cancel)
            )
            summary = summary_to_json(result, setup, seconds=monotonic.perf_counter() - started)
            await asyncio.to_thread(self._save, row.id, result)
            await asyncio.to_thread(
                partial(
                    self._store.update_backtest,
                    row.id,
                    state="done",
                    progress=1.0,
                    summary=json.dumps(summary),
                    finished_at=self._clock.now(),
                )
            )
            self._ended(row.id, "done", None)
        except Cancelled:
            await self._fail(row.id, "cancelled", None)
        except asyncio.CancelledError:
            cancel.set()
            await self._fail(row.id, "failed", "The program stopped during the backtest.")
            raise
        except Exception as exc:
            log.error("backtest_crashed", backtest=row.id, exc_info=True)
            await self._fail(row.id, "failed", f"{type(exc).__name__}: {exc}")
        finally:
            if self._active is not None and self._active.row.id == row.id:
                self._active = None

    def _prices(self, setup: BacktestSetup) -> Prices:
        windows = setup.all_windows()
        longest_chain_s = (max(s.max_steps for s in setup.strategies) + 1) * (
            setup.duration_s + setup.step_delay_s + setup.order_delay_s + 2
        )
        warmup = WARMUP_CANDLES * setup.duration_s if OpenRule.BREAKOUT in setup.opens else 0
        first = min(int(w.start.timestamp()) for w in windows) - 5 - warmup
        last = int(max(w.end.timestamp() for w in windows) + longest_chain_s) + setup.duration_s
        times, quotes = self._store.load(setup.asset, first, last)
        return Prices(times, quotes, self._store.coverage(setup.asset))

    def _save(self, backtest_id: int, result: BacktestResult) -> None:
        rows: list[ChainRow] = []
        seq: dict[int, int] = {}
        for chain in result.chains:
            n = seq[chain.run] = seq.get(chain.run, 0) + 1
            rows.append(
                ChainRow(
                    strategy=chain.run,
                    seq=n,
                    day=chain.day.isoformat(),
                    pair_no=chain.pair_no,
                    origin=chain.origin.value,
                    started=chain.started,
                    status=chain.status.value,
                    steps=len(chain.trades),
                    profit=str(chain.profit),
                    trades=json.dumps(
                        [
                            [
                                t.start,
                                t.end,
                                t.direction.value,
                                str(t.stake),
                                t.entry,
                                t.exit,
                                str(t.profit),
                            ]
                            for t in chain.trades
                        ]
                    ),
                )
            )
        self._store.add_chains(backtest_id, rows)

    async def _fail(self, backtest_id: int, state: str, error: str | None) -> None:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(
                partial(
                    self._store.update_backtest,
                    backtest_id,
                    state=state,
                    error=error,
                    finished_at=self._clock.now(),
                )
            )
        self._ended(backtest_id, state, error)

    def _ended(self, backtest_id: int, state: str, error: str | None) -> None:
        log.info("backtest_ended", backtest=backtest_id, state=state, error=error)
        self._publish(backtest_id, state, error)

    def _progressed(self, backtest_id: int, share: float) -> None:
        self._publish(backtest_id, "running", f"{share:.0%}")
        self._tasks.spawn(
            asyncio.to_thread(
                partial(self._store.update_backtest, backtest_id, progress=round(share, 3))
            ),
            name=f"backtest_{backtest_id}_progress",
        )

    def _publish(self, job_id: int, state: str, detail: str | None = None) -> None:
        self._bus.publish(
            JobChanged(
                occurred_at=self._clock.now(),
                kind="backtest",
                job_id=job_id,
                state=state,
                detail=detail,
            )
        )


# ---- JSON shapes (stored with the run; the API reads them back) --------------------------------


def _default_name(setup: BacktestSetup) -> str:
    days = f"{setup.first_day:%Y-%m-%d}" + (
        "" if setup.last_day == setup.first_day else f" to {setup.last_day:%Y-%m-%d}"
    )
    return f"{setup.asset} {setup.duration_s // 60 or setup.duration_s}m, {days}"


def setup_to_json(setup: BacktestSetup) -> dict[str, Any]:
    return {
        "asset": setup.asset,
        "first_day": setup.first_day.isoformat(),
        "last_day": setup.last_day.isoformat(),
        "start_time": setup.start_time.isoformat("minutes"),
        "end_time": setup.end_time.isoformat("minutes"),
        "timezone": setup.timezone,
        "weekdays": list(setup.weekdays),
        "duration_s": setup.duration_s,
        "mode": setup.mode.value,
        "pause_s": setup.pause_s,
        "max_open_pairs": setup.max_open_pairs,
        "max_pairs": setup.max_pairs,
        "profit_target": None if setup.profit_target is None else str(setup.profit_target),
        "loss_limit": None if setup.loss_limit is None else str(setup.loss_limit),
        "base_stake": str(setup.base_stake),
        "payout_pct": str(setup.payout_pct),
        "order_delay_s": setup.order_delay_s,
        "step_delay_s": setup.step_delay_s,
        "opens": [o.value for o in setup.opens],
        "market": {
            "pattern": setup.market.pattern.value,
            "candles": setup.market.candles,
            "misses": setup.market.misses,
            "width": setup.market.width,
            "net_share": setup.market.net_share,
            "breakout_candles": setup.market.breakout_candles,
            "breakout_by": setup.market.breakout_by.value,
        },
        "trend_max_candles": setup.trend_max_candles,
        "check_first_day": None
        if setup.check_first_day is None
        else setup.check_first_day.isoformat(),
        "check_last_day": None
        if setup.check_last_day is None
        else setup.check_last_day.isoformat(),
        "strategies": [
            {
                "strategy": s.strategy.value,
                "max_steps": s.max_steps,
                "multipliers": [str(m) for m in s.multipliers],
            }
            for s in setup.strategies
        ],
    }


def setup_from_json(data: dict[str, Any]) -> BacktestSetup:
    def money(value: object) -> Decimal | None:
        return None if value is None else Decimal(str(value))

    def day(value: object) -> date | None:
        return None if value is None else date.fromisoformat(str(value))

    # backtests from before Phase 31 have no ways of opening, no market rules, no second period
    market = data.get("market") or {}

    return BacktestSetup(
        asset=data["asset"],
        first_day=datetime.fromisoformat(data["first_day"]).date(),
        last_day=datetime.fromisoformat(data["last_day"]).date(),
        start_time=time.fromisoformat(data["start_time"]),
        end_time=time.fromisoformat(data["end_time"]),
        timezone=data["timezone"],
        weekdays=tuple(data["weekdays"]),
        duration_s=int(data["duration_s"]),
        mode=SessionMode(data["mode"]),
        pause_s=int(data["pause_s"]),
        max_open_pairs=int(data["max_open_pairs"]),
        max_pairs=data["max_pairs"],
        profit_target=money(data["profit_target"]),
        loss_limit=money(data["loss_limit"]),
        base_stake=Decimal(data["base_stake"]),
        payout_pct=Decimal(data["payout_pct"]),
        order_delay_s=float(data["order_delay_s"]),
        step_delay_s=float(data["step_delay_s"]),
        strategies=tuple(
            StrategySetup(
                Strategy(s["strategy"]),
                int(s["max_steps"]),
                tuple(Decimal(m) for m in s["multipliers"]),
            )
            for s in data["strategies"]
        ),
        opens=tuple(OpenRule(o) for o in data.get("opens", [OpenRule.WINDOW.value])),
        market=MarketRules(
            pattern=Pattern(market.get("pattern", Pattern.ALTERNATING.value)),
            candles=int(market.get("candles", 5)),
            misses=int(market.get("misses", 1)),
            width=float(market.get("width", 2.0)),
            net_share=float(market.get("net_share", 0.2)),
            breakout_candles=int(market.get("breakout_candles", 2)),
            breakout_by=BreakBy(market.get("breakout_by", BreakBy.CLOSE.value)),
        ),
        trend_max_candles=data.get("trend_max_candles", 20),
        check_first_day=day(data.get("check_first_day")),
        check_last_day=day(data.get("check_last_day")),
    )


def _strategy_json(s: StrategySetup) -> dict[str, Any]:
    return {
        "strategy": s.strategy.value,
        "max_steps": s.max_steps,
        "multipliers": [str(m) for m in s.multipliers],
    }


def _runs(result: BacktestResult, setup: BacktestSetup) -> list[Run]:
    return result.runs or setup.runs()


def _at(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=epoch)).isoformat()


def totals_to_json(total: Totals) -> dict[str, Any]:
    return {
        "windows": total.windows,
        "pairs": total.pairs,
        "chains": total.chains,
        "trades": total.trades,
        "trades_won": total.trades_won,
        "won_at_step": total.won_at_step,
        "exhausted": total.exhausted,
        "no_data_chains": total.no_data_chains,
        "skipped_rounds": total.skipped_rounds,
        "no_data_rounds": total.no_data_rounds,
        "profit": str(total.profit),
        "staked": str(total.staked),
        "largest_stake": str(total.largest_stake),
        "most_in_play": str(total.most_in_play),
        "worst_drawdown": str(total.worst_drawdown),
        "worst_drawdown_at": _at(total.worst_drawdown_at),
        "longest_losing_run": total.longest_losing_run,
        "spans": total.spans,
        "active_s": round(total.active_s),
        "stops": total.stops,
        "days": [
            {"day": day, "profit": str(v[0]), "chains": int(v[1]), "lost": int(v[2])}
            for day, v in sorted(total.days.items())
        ],
        "equity": [{"at": _at(at), "profit": str(profit)} for at, profit in total.equity],
    }


def summary_to_json(
    result: BacktestResult, setup: BacktestSetup, *, seconds: float
) -> dict[str, Any]:
    return {
        "windows": result.windows,
        "seconds": round(seconds, 1),
        "strategies": [
            {
                **_strategy_json(setup.strategies[run.strategy]),
                "index": run.strategy,
                "opens": run.opens.value,
                "period": run.period,
                **totals_to_json(total),
            }
            for run, total in zip(_runs(result, setup), result.totals, strict=True)
        ],
    }
