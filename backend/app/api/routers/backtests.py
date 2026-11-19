"""Backtests (decision D-84): replay a session-shaped setup on stored prices. A run goes in the
background, one at a time; `job.changed` events say when it moves on. Nothing is traded."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.api.deps import BacktestsDep
from app.api.schemas.backtests import (
    BacktestChainOut,
    BacktestChainsOut,
    BacktestIn,
    BacktestItemOut,
    BacktestOut,
    BacktestsOut,
    BacktestSummaryOut,
    BacktestTradeOut,
)
from app.backtest.replay import BacktestSetup, StrategySetup
from app.backtest.store import BacktestRow, ChainRow
from app.domain.enums import ChainStatus, Direction

router = APIRouter(prefix="/backtests", tags=["backtests"])


def _setup(body: BacktestIn) -> BacktestSetup:
    return BacktestSetup(
        asset=body.asset,
        first_day=body.first_day,
        last_day=body.last_day,
        start_time=body.start_time,
        end_time=body.end_time,
        timezone=body.timezone,
        weekdays=tuple(sorted(body.weekdays)),
        duration_s=body.duration_s,
        mode=body.mode,
        pause_s=body.pause_s,
        max_open_pairs=body.max_open_pairs,
        max_pairs=body.max_pairs,
        profit_target=body.profit_target,
        loss_limit=body.loss_limit,
        base_stake=body.base_stake,
        payout_pct=body.payout_pct,
        order_delay_s=body.order_delay_s,
        step_delay_s=body.step_delay_s,
        strategies=tuple(
            StrategySetup(s.strategy, s.max_steps, tuple(s.multipliers)) for s in body.strategies
        ),
    )


def _item(row: BacktestRow) -> tuple[dict[str, Any], dict[str, Any]]:
    setup: dict[str, Any] = json.loads(row.setup)
    item = {
        "id": row.id,
        "name": row.name,
        "state": row.state,
        "progress": row.progress,
        "error": row.error,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
        "asset": setup["asset"],
        "first_day": setup["first_day"],
        "last_day": setup["last_day"],
        "strategies": [s["strategy"] for s in setup["strategies"]],
    }
    return item, setup


def backtest_out(row: BacktestRow) -> BacktestOut:
    item, setup = _item(row)
    summary = (
        None if row.summary is None else BacktestSummaryOut.model_validate(json.loads(row.summary))
    )
    return BacktestOut(**item, setup=BacktestIn.model_validate(setup), summary=summary)


def _at(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


def chain_out(row: ChainRow) -> BacktestChainOut:
    return BacktestChainOut(
        strategy=row.strategy,
        seq=row.seq,
        day=datetime.fromisoformat(row.day).date(),
        pair_no=row.pair_no,
        origin=Direction(row.origin),
        started=_at(row.started),
        status=ChainStatus(row.status),
        steps=row.steps,
        profit=Decimal(row.profit),
        trades=[
            BacktestTradeOut(
                start=_at(start),
                end=_at(end),
                direction=Direction(direction),
                stake=stake,
                entry=entry,
                exit=exit_,
                profit=profit,
            )
            for start, end, direction, stake, entry, exit_, profit in json.loads(row.trades)
        ],
    )


@router.post("", response_model=BacktestOut, status_code=status.HTTP_202_ACCEPTED)
async def start_backtest(body: BacktestIn, backtests: BacktestsDep) -> BacktestOut:
    """Replay the setup on the stored prices, every strategy on the same prices, in the
    background. 422 `invalid_backtest` (no window on those days, no prices stored), 409
    `backtest_running`."""
    return backtest_out(await backtests.start(_setup(body), body.name))


@router.get("", response_model=BacktestsOut)
async def list_backtests(backtests: BacktestsDep) -> BacktestsOut:
    """The latest backtests, newest first (without their results)."""
    return BacktestsOut(
        items=[BacktestItemOut(**_item(row)[0]) for row in await backtests.recent()]
    )


@router.get("/{backtest_id}", response_model=BacktestOut)
async def get_backtest(backtest_id: int, backtests: BacktestsDep) -> BacktestOut:
    """One backtest: its setup and, once done, the figures of each strategy."""
    return backtest_out(await backtests.get(backtest_id))


@router.get("/{backtest_id}/chains", response_model=BacktestChainsOut)
async def list_chains(
    backtest_id: int,
    backtests: BacktestsDep,
    strategy: Annotated[int | None, Query(ge=0, le=5)] = None,
    chain_status: Annotated[ChainStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BacktestChainsOut:
    """The chains of a backtest in time order, with every trade (filter by strategy index and
    by `status`: `completed`, `exhausted`, `failed`)."""
    rows, total = await backtests.chains(
        backtest_id,
        strategy=strategy,
        status=None if chain_status is None else chain_status.value,
        limit=limit,
        offset=offset,
    )
    return BacktestChainsOut(items=[chain_out(row) for row in rows], total=total)


@router.post("/{backtest_id}/cancel", response_model=BacktestOut)
async def cancel_backtest(backtest_id: int, backtests: BacktestsDep) -> BacktestOut:
    """Stop a running backtest (nothing of it is kept but the setup)."""
    return backtest_out(await backtests.cancel(backtest_id))


@router.delete("/{backtest_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backtest(backtest_id: int, backtests: BacktestsDep) -> Response:
    await backtests.delete(backtest_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
