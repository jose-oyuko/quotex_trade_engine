"""`npm run backtest`: the strategies as typed, and a run on stored prices printed as a table."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, date, datetime
from datetime import time as clock
from decimal import Decimal
from pathlib import Path

import pytest

from app.backtest.replay import BacktestSetup, OpenRule, StrategySetup
from app.backtest.store import BacktestStore
from app.core.config import Settings
from app.domain.enums import SessionMode, Strategy
from scripts.backtest import opens, run, run_label, strategy, window

T10 = int(datetime(2023, 11, 15, 10, 0, tzinfo=UTC).timestamp())


def test_a_strategy_is_typed_as_name_and_multipliers() -> None:
    assert strategy("martingale:2,4,8") == StrategySetup(
        Strategy.MARTINGALE, 3, (Decimal(2), Decimal(4), Decimal(8))
    )
    assert strategy("no_martingale") == StrategySetup(Strategy.NO_MARTINGALE, 0, ())
    with pytest.raises(argparse.ArgumentTypeError, match="at most 8 steps"):
        strategy("growing_flip:" + ",".join(["2"] * 9))
    with pytest.raises(argparse.ArgumentTypeError, match="not a strategy"):
        strategy("double_or_nothing:2")
    assert window("10:00-14:30") == (clock(10, 0), clock(14, 30))
    assert opens("window,breakout") == (OpenRule.WINDOW, OpenRule.BREAKOUT)
    with pytest.raises(argparse.ArgumentTypeError):
        opens("sometimes")
    assert run_label({"strategy": "martingale"}) == "martingale"
    assert run_label({"strategy": "martingale", "opens": "breakout", "period": 2}) == (
        "martingale trend (2)"
    )


async def test_a_run_prints_the_strategies_side_by_side(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)  # type: ignore[call-arg]
    store = BacktestStore(settings.history_path)
    store.prepare(datetime.now(UTC))
    times = list(range(T10 - 60, T10 + 3600))
    store.add("1HZ75V", times, [100.0] * len(times))
    store.cover("1HZ75V", times[0], times[-1])
    setup = BacktestSetup(
        asset="1HZ75V",
        first_day=date(2023, 11, 15),
        last_day=date(2023, 11, 15),
        start_time=clock(10, 0),
        end_time=clock(10, 10),
        timezone="UTC",
        weekdays=(0, 1, 2, 3, 4, 5, 6),
        duration_s=60,
        mode=SessionMode.SEQUENTIAL,
        pause_s=0,
        max_open_pairs=1,
        max_pairs=None,
        profit_target=None,
        loss_limit=None,
        base_stake=Decimal(1),
        strategies=(strategy("no_martingale"), strategy("martingale:2")),
    )
    assert await run(settings, setup) == 0
    out = capsys.readouterr().out
    assert "assumed payout 88%" in out
    assert "no_martingale" in out and "martingale" in out
    assert "lost every step" in out
    assert len(store.backtests()) == 1  # kept, so the dashboard shows it too
    assert await run(settings, replace(setup, asset="R_75")) == 2  # no prices stored
    assert "download them first" in capsys.readouterr().err
    both = replace(
        setup,
        opens=(OpenRule.WINDOW, OpenRule.BREAKOUT),
        check_first_day=date(2023, 11, 15),
        check_last_day=date(2023, 11, 15),
    )
    assert await run(settings, both) == 0
    out = capsys.readouterr().out
    assert "martingale trend (2)" in out and "hours open" in out
    assert "the second period, which judges" in out
