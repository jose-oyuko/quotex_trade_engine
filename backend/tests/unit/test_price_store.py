"""The price store (decision D-84): ticks, what was downloaded, and the downloads."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.backtest.store import PriceStore, merge, subtract
from app.deriv.protocol import named_assets, parse_ticks_history, ticks_history_request

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def store(tmp_path: Path) -> PriceStore:
    s = PriceStore(tmp_path / "history.db")
    s.prepare(NOW)
    return s


def test_ranges_are_merged_where_they_overlap_or_touch() -> None:
    assert merge([(10, 20), (21, 30), (5, 12), (40, 50), (60, 59)]) == [(5, 30), (40, 50)]


def test_the_missing_parts_of_a_period_are_its_gaps() -> None:
    assert subtract((0, 100), []) == [(0, 100)]
    assert subtract((0, 100), [(10, 20), (50, 100)]) == [(0, 9), (21, 49)]
    assert subtract((0, 100), [(-5, 200)]) == []
    assert subtract((30, 40), [(0, 10), (35, 36), (90, 99)]) == [(30, 34), (37, 40)]


def test_ticks_are_stored_once_and_counted(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert s.add("R_75", [100, 102, 104], [1.5, 1.6, 1.7]) == 3
    assert s.add("R_75", [104, 106], [9.9, 1.8]) == 1  # 104 is kept as it was
    times, quotes = s.load("R_75", 101, 106)
    assert list(times) == [102, 104, 106]
    assert list(quotes) == [1.6, 1.7, 1.8]
    assert s.load("EURUSD", 0, 10**10)[0].tolist() == []
    [held] = s.held()
    assert (held.asset, held.ticks, held.first, held.last) == ("R_75", 4, 100, 106)


def test_what_was_downloaded_is_kept_as_ranges(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.cover("R_75", 100, 200)
    s.cover("R_75", 201, 300)
    s.cover("R_75", 500, 600)
    assert s.coverage("R_75") == [(100, 300), (500, 600)]
    assert s.missing("R_75", 0, 700) == [(0, 99), (301, 499), (601, 700)]
    assert s.missing("1HZ75V", 0, 10) == [(0, 10)]


def test_forgetting_an_asset_removes_its_prices_and_ranges(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.add("R_75", [1, 2], [1.0, 2.0])
    s.cover("R_75", 1, 2)
    s.add("1HZ75V", [1], [5.0])
    assert s.forget("R_75") is True
    assert s.forget("R_75") is False
    assert [h.asset for h in s.held()] == ["1HZ75V"]
    assert s.coverage("R_75") == []


def test_downloads_are_recorded_and_a_cut_one_is_marked_failed_at_start(tmp_path: Path) -> None:
    s = store(tmp_path)
    row = s.new_download("R_75", 100, 200, NOW)
    assert (row.state, row.ticks, row.reached) == ("running", 0, None)
    s.update_download(row.id, ticks=50, reached=150)
    assert PriceStore(s.path).prepare(NOW, cut_running=False) == 0  # the terminal command
    assert s.download(row.id).state == "running"  # type: ignore[union-attr]
    assert PriceStore(s.path).prepare(NOW) == 1  # the application starting again
    found = s.download(row.id)
    assert found is not None
    assert (found.state, found.ticks, found.reached) == ("failed", 50, 150)
    assert found.error == "The program stopped during the download."
    assert [d.id for d in s.downloads()] == [row.id]


def test_deriv_s_history_answer_is_read_oldest_first() -> None:
    assert ticks_history_request("R_75", start=1, end=9, count=5000) == {
        "ticks_history": "R_75",
        "start": 1,
        "end": "9",
        "count": 5000,
        "style": "ticks",
    }
    reply = {"history": {"times": [3, 1, "2", True, 4], "prices": [3.5, 1.5, 2.5, 9, "x"]}}
    assert parse_ticks_history(reply) == ([1, 2, 3], [1.5, 2.5, 3.5])
    assert parse_ticks_history({"msg_type": "history"}) == ([], [])


def test_deriv_s_asset_list_gives_each_code_its_everyday_name() -> None:
    rows = [
        {
            "underlying_symbol": "1HZ100V",
            "underlying_symbol_name": "Volatility 100 (1s) Index",
            "market": "synthetic_index",
            "submarket": "random_index",
        },
        {
            "underlying_symbol": "R_10",
            "underlying_symbol_name": "Volatility 10 Index",
            "market": "synthetic_index",
            "submarket": "random_index",
        },
        {
            "underlying_symbol": "1HZ25V",
            "underlying_symbol_name": "Volatility 25 (1s) Index",
            "market": "synthetic_index",
            "submarket": "random_index",
        },
        {
            "underlying_symbol": "frxEURUSD",
            "underlying_symbol_name": "EUR/USD",
            "market": "forex",
            "submarket": "major_pairs",
        },
        {
            "underlying_symbol": "cryBTCUSD",
            "underlying_symbol_name": "BTC/USD",
            "market": "cryptocurrency",
            "submarket": "non_stable_coin",
        },
        {"underlying_symbol_name": "no symbol"},
        "not a row",
    ]
    assert named_assets(rows) == [
        ("cryBTCUSD", "BTC/USD", "Cryptocurrency"),
        ("EURUSD", "EUR/USD", "Forex"),  # our code for a forex pair
        ("R_10", "Volatility 10 Index", "Volatility indices"),
        ("1HZ25V", "Volatility 25 (1s) Index", "Volatility indices"),
        ("1HZ100V", "Volatility 100 (1s) Index", "Volatility indices"),
    ]
    assert named_assets(None) == []
