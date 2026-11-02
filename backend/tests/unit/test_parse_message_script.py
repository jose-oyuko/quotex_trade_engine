from __future__ import annotations

from pathlib import Path

import pytest

from scripts.parse_message import parse_args, run
from tests.signal_messages import ENTRY_CONFIRMED


async def try_message(*argv: str) -> int:
    return await run(parse_args(list(argv)))


async def test_a_signal_is_shown_with_its_trade(capsys: pytest.CaptureFixture[str]) -> None:
    assert await try_message("EURUSD PUT 1m", "--suffix", "otc") == 0
    out = capsys.readouterr().out
    assert "Status : parsed" in out
    assert "PUT EURUSD_otc for 60 s" in out
    assert "now" in out


async def test_a_non_signal_shows_its_reason(capsys: pytest.CaptureFixture[str]) -> None:
    assert await try_message("great day team") == 0
    out = capsys.readouterr().out
    assert "Status : not_parsed" in out and "Reason : no known signal format found" in out


async def test_entry_times_are_judged_against_the_chosen_moment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    message = tmp_path / "m.txt"
    message.write_text(ENTRY_CONFIRMED, encoding="utf-8")
    base = ["--file", str(message), "--suffix", "auto"]

    await try_message(*base, "--now", "2026-11-01T07:20:00+00:00")
    assert "at 2026-11-01 07:29:00 UTC (scheduled)" in capsys.readouterr().out

    await try_message(*base, "--now", "2026-11-01T09:00:00+00:00")
    out = capsys.readouterr().out
    assert "Status : ignored" in out and "already passed" in out


async def test_bad_input_is_explained_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await try_message() == 2
    assert await try_message("x", "--tz", "Mars/Base") == 2
    assert await try_message("x", "--now", "yesterday") == 2
    assert await try_message("--file", str(tmp_path / "missing.txt")) == 2
    out = capsys.readouterr().out
    assert "Give the message" in out and "Bad option" in out and "Cannot read" in out
