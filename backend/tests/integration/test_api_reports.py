"""/api/v1/reports: the same hand-made history as `test_reports.py`, through HTTP."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import pytest

from tests.api_support import running_api
from tests.reports_support import seed_hand_made_history

API = "/api/v1/reports"


async def seed(factory: Any) -> None:
    await seed_hand_made_history(factory)


def api(tmp_path: Path, **kwargs: Any):  # type: ignore[no-untyped-def]
    return running_api(tmp_path, seed=seed, **kwargs)


# --- summary -------------------------------------------------------------------------------------


async def test_the_summary_reports_the_demo_account_by_default(tmp_path: Path) -> None:
    async with api(tmp_path) as rig:
        body = (await rig.client.get(f"{API}/summary")).json()
    assert body["filter"]["account_type"] == "demo"
    m = body["metrics"]
    assert (m["trades"], m["wins"], m["losses"], m["draws"]) == (9, 4, 5, 0)
    assert m["profit"] == "-2.50" and m["staked"] == "19.00"  # money is text
    assert m["win_rate"] == pytest.approx(4 / 9) and m["roi"] == pytest.approx(-2.5 / 19)
    assert m["avg_stake"] == "2.11" and m["sample"] == "tiny"
    assert body["not_counted"] == {"failed": 1, "unknown": 1, "open": 1}
    assert body["streaks"] == {"longest_win": 2, "longest_loss": 4, "current": 2}
    assert body["drawdown"] == {
        "max_amount": "9.00",
        "peak_day": "2026-11-02",
        "trough_day": "2026-11-03",
        "current_amount": "3.90",
    }
    assert body["expectation"]["verdict"] == "not_enough_data"
    assert body["expectation"]["z_score"] == pytest.approx(-0.639, abs=1e-2)
    assert (body["first_day"], body["last_day"]) == ("2026-11-02", "2026-11-04")
    assert body["sample_guide"] == {"tiny_below": 10, "small_below": 30}


async def test_real_money_is_a_separate_report(tmp_path: Path) -> None:
    async with api(tmp_path) as rig:
        body = (await rig.client.get(f"{API}/summary", params={"account_type": "real"})).json()
    assert body["filter"]["account_type"] == "real"
    assert body["metrics"]["trades"] == 1 and body["metrics"]["profit"] == "0.80"


@pytest.mark.parametrize(
    ("params", "trades", "profit"),
    [
        ({"group_id": 1}, 6, "-5.60"),
        ({"group_id": 2}, 3, "3.10"),
        ({"asset": "EURUSD"}, 4, "3.10"),
        ({"strategy": "flip_every_loss"}, 3, "3.10"),
        ({"strategy": "martingale", "asset": "GBPUSD"}, 3, "-7.00"),
        ({"from": "2026-11-03T00:00:00Z"}, 6, "-3.90"),
        ({"to": "2026-11-03T00:00:00Z"}, 3, "1.40"),
        ({"from": "2026-11-02T10:10:00Z", "to": "2026-11-02T14:31:00Z"}, 2, "2.40"),
        # the same instants written in another zone (UTC+3): 13:10 and 17:31
        ({"from": "2026-11-02T13:10:00+03:00", "to": "2026-11-02T17:31:00+03:00"}, 2, "2.40"),
        ({"group_id": 99}, 0, "0.00"),
    ],
)
async def test_the_filters_narrow_the_numbers(
    tmp_path: Path, params: dict[str, str | int], trades: int, profit: str
) -> None:
    async with api(tmp_path) as rig:
        body = (await rig.client.get(f"{API}/summary", params=params)).json()
    assert body["metrics"]["trades"] == trades and body["metrics"]["profit"] == profit


async def test_the_filters_are_echoed_back(tmp_path: Path) -> None:
    async with api(tmp_path) as rig:
        body = (
            await rig.client.get(
                f"{API}/summary",
                params={
                    "from": "2026-11-02T13:10:00+03:00",
                    "group_id": 1,
                    "utc_offset_minutes": -180,
                },
            )
        ).json()
    assert body["filter"] == {
        "account_type": "demo",
        "since": "2026-11-02T10:10:00Z",  # normalised to UTC
        "until": None,
        "group_id": 1,
        "strategy": None,
        "asset": None,
        "utc_offset_minutes": -180,
    }


@pytest.mark.parametrize(
    ("params", "code", "fragment"),
    [
        ({"from": "2026-11-02T00:00:00"}, "invalid_range", "time zone"),
        ({"to": "2026-11-02 00:00:00"}, "invalid_range", "time zone"),
        (
            {"from": "2026-11-03T00:00:00Z", "to": "2026-11-02T00:00:00Z"},
            "invalid_range",
            "before its end",
        ),
        (
            {"from": "2026-11-02T00:00:00Z", "to": "2026-11-02T00:00:00Z"},
            "invalid_range",
            "before its end",
        ),
        ({"from": "yesterday"}, "validation_error", "datetime"),
        ({"account_type": "paper"}, "validation_error", "Input should be"),
        ({"strategy": "yolo"}, "validation_error", "Input should be"),
        ({"utc_offset_minutes": 841}, "validation_error", "less than or equal"),
        ({"utc_offset_minutes": "x"}, "validation_error", "integer"),
        ({"group_id": "x"}, "validation_error", "integer"),
        ({"asset": ""}, "validation_error", "at least 1"),
        ({"asset": "X" * 33}, "validation_error", "at most 32"),
    ],
)
async def test_bad_filters_are_refused_with_the_reason(
    tmp_path: Path, params: dict[str, str | int], code: str, fragment: str
) -> None:
    async with api(tmp_path) as rig:
        response = await rig.client.get(f"{API}/summary", params=params)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == code and fragment in response.text


# --- the other reports ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("by", "expected"),
    [
        ("group", [("Beta", 3, "3.10"), ("Alpha", 6, "-5.60")]),
        ("asset", [("EURUSD", 4, "3.10"), ("GBPUSD", 5, "-5.60")]),
        ("strategy", [("flip_every_loss", 3, "3.10"), ("martingale", 6, "-5.60")]),
    ],
)
async def test_the_breakdowns(
    tmp_path: Path, by: str, expected: list[tuple[str, int, str]]
) -> None:
    async with api(tmp_path) as rig:
        body = (await rig.client.get(f"{API}/breakdown", params={"by": by})).json()
    assert body["by"] == by
    assert [
        (r["label"], r["metrics"]["trades"], r["metrics"]["profit"]) for r in body["rows"]
    ] == expected


async def test_hour_and_weekday_breakdowns_have_every_bar_and_follow_the_owners_clock(
    tmp_path: Path,
) -> None:
    async with api(tmp_path) as rig:
        hours = (await rig.client.get(f"{API}/breakdown", params={"by": "hour"})).json()["rows"]
        weekdays = (await rig.client.get(f"{API}/breakdown", params={"by": "weekday"})).json()[
            "rows"
        ]
        shifted = (
            await rig.client.get(
                f"{API}/breakdown", params={"by": "hour", "utc_offset_minutes": -180}
            )
        ).json()["rows"]
    assert [r["label"] for r in hours][:3] == ["00:00", "01:00", "02:00"] and len(hours) == 24
    assert {r["key"]: r["metrics"]["trades"] for r in hours if r["metrics"]["trades"]} == {
        "0": 1, "9": 3, "10": 2, "12": 1, "14": 1, "23": 1,
    }  # fmt: skip
    assert [r["label"] for r in weekdays] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert [r["metrics"]["trades"] for r in weekdays] == [3, 4, 2, 0, 0, 0, 0]
    assert {r["key"]: r["metrics"]["trades"] for r in shifted if r["metrics"]["trades"]} == {
        "6": 3, "7": 2, "9": 1, "11": 1, "20": 1, "21": 1,
    }  # fmt: skip


async def test_the_breakdown_needs_to_know_how_to_split(tmp_path: Path) -> None:
    async with api(tmp_path) as rig:
        assert (await rig.client.get(f"{API}/breakdown")).status_code == 422
        assert (
            await rig.client.get(f"{API}/breakdown", params={"by": "colour"})
        ).status_code == 422


async def test_the_equity_curve(tmp_path: Path) -> None:
    async with api(tmp_path) as rig:
        body = (await rig.client.get(f"{API}/equity")).json()
    assert [(p["day"], p["trades"], p["profit"], p["cumulative"]) for p in body["points"]] == [
        ("2026-11-02", 3, "1.40", "1.40"),
        ("2026-11-03", 4, "-9.00", "-7.60"),
        ("2026-11-04", 2, "5.10", "-2.50"),
    ]


async def test_the_chain_depth(tmp_path: Path) -> None:
    async with api(tmp_path) as rig:
        body = (await rig.client.get(f"{API}/depth")).json()
    assert (body["chains"], body["completed"], body["exhausted"], body["other"]) == (5, 4, 1, 0)
    assert body["avg_chain_profit"] == "-0.50"
    first, second, third = body["steps"]
    assert (first["step"], first["chains_reaching"], first["share_of_chains"]) == (1, 5, 1.0)
    assert (second["chains_reaching"], second["share_of_chains"]) == (3, 0.6)
    assert (third["chains_reaching"], third["profit"], third["chain_profit_ending_here"]) == (
        1,
        "-4.00",
        "-7.00",
    )


async def test_a_report_with_nothing_to_show_is_empty_not_an_error(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:  # an empty database
        summary = (await rig.client.get(f"{API}/summary")).json()
        assert summary["metrics"]["trades"] == 0 and summary["metrics"]["win_rate"] is None
        assert (await rig.client.get(f"{API}/equity")).json()["points"] == []
        assert (await rig.client.get(f"{API}/depth")).json()["chains"] == 0
        by_group = (await rig.client.get(f"{API}/breakdown", params={"by": "group"})).json()
        assert by_group["rows"] == []


# --- CSV -----------------------------------------------------------------------------------------


def parse(raw: bytes, delimiter: str = ",") -> list[list[str]]:
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), delimiter=delimiter))


async def test_the_trades_csv_is_utf8_with_a_byte_order_mark_and_windows_line_endings(
    tmp_path: Path,
) -> None:
    async with api(tmp_path) as rig:
        response = await rig.client.get(f"{API}/export/trades.csv")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="quotex-trades-demo-'
    )
    assert response.headers["content-disposition"].endswith('.csv"')
    raw = response.content
    assert raw.startswith(b"\xef\xbb\xbf")  # the byte-order mark Excel needs to read UTF-8
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")  # every line ends CRLF


async def test_the_trades_csv_has_one_row_per_demo_trade_with_plain_numbers(tmp_path: Path) -> None:
    async with api(tmp_path) as rig:
        rows = parse((await rig.client.get(f"{API}/export/trades.csv")).content)
    header, *trades = rows
    assert header[:6] == [
        "created_at_utc",
        "settled_at_utc",
        "account",
        "group_id",
        "group",
        "strategy",
    ]
    assert len(trades) == 12  # t1..t12: every status, demo only (not the real trade t13)
    by_status: dict[str, int] = {}
    for row in trades:
        by_status[row[header.index("status")]] = by_status.get(row[header.index("status")], 0) + 1
    assert by_status == {"won": 4, "lost": 5, "failed": 1, "unknown": 1, "open": 1}
    first = dict(zip(header, trades[0], strict=True))
    assert first["account"] == "demo" and first["group"] == "Alpha" and first["asset"] == "EURUSD"
    assert (first["step"], first["stake"], first["profit"], first["payout_pct"]) == (
        "1",
        "1.00",
        "-1.00",
        "80",
    )
    assert first["settled_at_utc"] == "2026-11-02 10:05:00"
    assert first["strategy"] == "martingale" and first["direction"] == "call"
    unsettled = next(
        dict(zip(header, r, strict=True)) for r in trades if r[header.index("status")] == "failed"
    )
    assert (unsettled["settled_at_utc"], unsettled["profit"], unsettled["payout_pct"]) == (
        "",
        "",
        "",
    )
    for row in trades:  # money always has a dot, never a comma, and a loss stays a number
        profit = row[header.index("profit")]
        assert profit == "" or profit.replace("-", "").replace(".", "").isdigit()


async def test_the_semicolon_version_for_excel_in_many_locales(tmp_path: Path) -> None:
    async with api(tmp_path) as rig:
        raw = (
            await rig.client.get(f"{API}/export/trades.csv", params={"delimiter": "semicolon"})
        ).content
    header, *trades = parse(raw, ";")
    assert len(header) == 17 and len(trades) == 12
    assert (
        "," not in raw.decode("utf-8-sig").splitlines()[1].split(";")[10]
    )  # money still has a dot
    assert (await running_api_status(tmp_path, {"delimiter": "tab"})) == 422


async def running_api_status(tmp_path: Path, params: dict[str, str]) -> int:
    async with api(tmp_path / "again") as rig:
        return (await rig.client.get(f"{API}/export/trades.csv", params=params)).status_code


async def test_the_csv_follows_the_filters_and_the_account(tmp_path: Path) -> None:
    async with api(tmp_path) as rig:
        real = parse(
            (
                await rig.client.get(f"{API}/export/trades.csv", params={"account_type": "real"})
            ).content
        )
        beta = parse(
            (await rig.client.get(f"{API}/export/trades.csv", params={"group_id": 2})).content
        )
        ranged = parse(
            (
                await rig.client.get(
                    f"{API}/export/trades.csv",
                    params={"from": "2026-11-03T00:00:00Z", "to": "2026-11-04T00:00:00Z"},
                )
            ).content
        )
    assert len(real) == 2 and real[1][2] == "real"  # header + t13
    assert len(beta) - 1 == 4  # t7 t8 t9 and the unknown t11
    assert len(ranged) - 1 == 4  # created on 11-03: t4 t5 t6 t7


async def test_the_csv_range_is_the_time_a_trade_was_created_so_unsettled_trades_are_included(
    tmp_path: Path,
) -> None:
    """t10 (failed), t11 (unknown) and t12 (open) were created on 11-04 at 13:00 and never settled:
    a range on the settle time could never find them."""
    async with api(tmp_path) as rig:
        response = await rig.client.get(
            f"{API}/export/trades.csv",
            params={"from": "2026-11-04T12:30:00Z", "to": "2026-11-05T00:00:00Z"},
        )
    header, *trades = parse(response.content)
    assert sorted(row[header.index("status")] for row in trades) == ["failed", "open", "unknown"]


async def test_text_that_a_spreadsheet_would_run_as_a_formula_is_made_harmless(
    tmp_path: Path,
) -> None:
    async def seed_nasty(factory: Any) -> None:
        await seed_hand_made_history(
            factory, titles=('=HYPERLINK("http://evil")', "Señales Ñandú €")
        )

    async with running_api(tmp_path, seed=seed_nasty) as rig:
        raw = (await rig.client.get(f"{API}/export/trades.csv")).content
    header, *trades = parse(raw)
    titles = {row[header.index("group")] for row in trades}
    assert titles == {'\'=HYPERLINK("http://evil")', "Señales Ñandú €"}  # defused; accents intact
    losses = {
        row[header.index("profit")] for row in trades if row[header.index("status")] == "lost"
    }
    assert "-1.00" in losses  # numbers are never touched, even though they start with "-"
    assert "Ñandú".encode() in raw  # really UTF-8 on the wire


async def test_the_breakdown_csv(tmp_path: Path) -> None:
    async with api(tmp_path) as rig:
        response = await rig.client.get(f"{API}/export/breakdown.csv", params={"by": "group"})
        semicolon = await rig.client.get(
            f"{API}/export/breakdown.csv", params={"by": "asset", "delimiter": "semicolon"}
        )
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert 'filename="quotex-by-group-demo-' in response.headers["content-disposition"]
    header, beta, alpha = parse(response.content)
    assert header[:8] == ["key", "label", "trades", "wins", "losses", "draws", "win_rate", "profit"]
    assert beta[:8] == ["2", "Beta", "3", "2", "1", "0", "0.6667", "3.10"]
    assert alpha[:8] == ["1", "Alpha", "6", "2", "4", "0", "0.3333", "-5.60"]
    assert alpha[-1] == "tiny"
    assert parse(semicolon.content, ";")[1][:3] == ["EURUSD", "EURUSD", "4"]
    assert (await rig_get(tmp_path, f"{API}/export/breakdown.csv")) == 422  # needs `by`


async def rig_get(tmp_path: Path, url: str) -> int:
    async with api(tmp_path / "other") as rig:
        return (await rig.client.get(url)).status_code
