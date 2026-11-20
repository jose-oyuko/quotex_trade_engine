"""`npm run market:scan`: candle lengths as typed, and a scan of stored prices printed."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.backtest.store import PriceStore
from app.core.config import Settings
from scripts.market_scan import length, main
from tests.unit.test_market_detector import T0, bars


def store_candles(settings: Settings, text: str) -> None:
    """Prices that make exactly the candles of `text`: open, high, low and close in each minute."""
    store = PriceStore(settings.history_path)
    store.prepare(datetime.now(UTC))
    times, quotes = [], []
    for c in bars(text):
        times += [c.start, c.start + 10, c.start + 20, c.start + 59]
        quotes += [c.open, c.high, c.low, c.close]
    store.add("1HZ75V", times, quotes)


def test_a_candle_length_is_a_name_or_seconds() -> None:
    assert (length("M1"), length("m5"), length("H1"), length("90"), length("15s")) == (
        60,
        300,
        3600,
        90,
        15,
    )
    with pytest.raises(argparse.ArgumentTypeError):
        length("weekly")


def test_a_scan_prints_the_comparisons(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)  # type: ignore[call-arg]
    store_candles(settings, "UDUDU BB UUU UDUDU BB U")
    start = datetime.fromtimestamp(T0, UTC).isoformat()
    end = datetime.fromtimestamp(T0 + 18 * 60, UTC).isoformat()
    period = ["--asset", "1HZ75V", "--from", start, "--to", end]

    assert main(period, settings) == 0
    out = capsys.readouterr().out
    assert "alternating 5, breakout: 2 by close" in out
    assert "consolidations: 2 (2 broke out)" in out
    assert "after a breakout: median 8 candles" in out

    assert main([*period, "--compare"], settings) == 0
    out = capsys.readouterr().out
    for pattern in ("alternating 5", "mixed 6, 1 miss", "tight 8, x2", "overlap 4", "choppy 10"):
        assert pattern in out


def test_a_scan_without_prices_or_with_bad_settings_says_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)  # type: ignore[call-arg]
    store_candles(settings, "UDUDU")
    period = ["--asset", "R_75", "--from", "2023-11-14T22:00", "--to", "2023-11-15T00:00"]
    assert main(period, settings) == 2
    assert "No prices of R_75" in capsys.readouterr().err
    wrong = [*period, "--asset", "1HZ75V", "--pattern", "mixed", "--candles", "4", "--misses", "3"]
    assert main(wrong, settings) == 2
    assert "misses" in capsys.readouterr().err
