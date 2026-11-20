"""/api/v1/market (decision D-85): candles and consolidation scans on stored (made-up) prices."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.market.detector import MarketRules, Pattern, scan
from app.services.market import load_candles
from tests.api_support import ApiRig, running_api
from tests.integration.test_api_backtests import download

API = "/api/v1"
DAY = "2023-11-15"
START, END = f"{DAY}T10:00:00Z", f"{DAY}T14:00:00Z"


async def scan_body(rig: ApiRig, **changes: Any) -> Any:
    body = {"asset": "1HZ75V", "start": START, "end": END, "length": 60} | changes
    return await rig.client.post(f"{API}/market/scan", json=body)


async def test_the_chart_reads_candles_of_any_length(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await download(rig, START, END)
        params = {"asset": "1HZ75V", "start": START, "end": END}
        m1 = (await rig.client.get(f"{API}/market/candles", params=params)).json()
        assert (m1["asset"], m1["length"], len(m1["items"])) == ("1HZ75V", 60, 240)
        first = m1["items"][0]
        assert first["start"] == START and first["ticks"] == 60
        assert first["low"] <= min(first["open"], first["close"])
        m5 = await rig.client.get(f"{API}/market/candles", params=params | {"length": 300})
        assert len(m5.json()["items"]) == 48
        # a start inside a candle is moved back to the candle's start
        odd = params | {"start": f"{DAY}T10:02:30Z", "length": 300}
        assert (await rig.client.get(f"{API}/market/candles", params=odd)).json()["start"] == START
        nothing = params | {"asset": "R_75"}
        assert (await rig.client.get(f"{API}/market/candles", params=nothing)).json()["items"] == []
        too_many = params | {"length": 1}
        refused = await rig.client.get(f"{API}/market/candles", params=too_many)
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == "invalid_market"
        assert "5,000 candles" in refused.json()["error"]["message"]


async def test_a_scan_finds_what_the_detector_finds_with_its_statistics(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        await download(rig, START, END)
        response = await scan_body(rig, rules={"pattern": "mixed", "candles": 6, "misses": 2})
        assert response.status_code == 200, response.text
        found = response.json()
        assert found["rules"] == {
            "pattern": "mixed",
            "candles": 6,
            "misses": 2,
            "width": 2.0,
            "net_share": 0.2,
            "breakout_candles": 2,
            "breakout_by": "close",
        }
        # the same as the detector on the same candles
        start = int(datetime.fromisoformat(START).timestamp())
        candles = load_candles(rig.app.state.market._store, "1HZ75V", start, start + 4 * 3600, 60)
        expected = scan(candles, MarketRules(Pattern.MIXED, candles=6, misses=2), 60)
        assert len(found["consolidations"]) == len(expected.consolidations) > 0
        assert len(found["trends"]) == len(expected.trends)
        cons = found["consolidations"][0]
        first = datetime.fromtimestamp(expected.consolidations[0].first, UTC)
        assert datetime.fromisoformat(cons["first"]) == first
        assert cons["candles"] >= 6 and cons["low"] <= cons["high"]
        stats = found["stats"]
        assert stats["candles"] == 240 == len(candles)
        assert stats["consolidations"] == len(expected.consolidations)
        assert (
            0 <= stats["deep_any"]["low"] <= stats["deep_any"]["share"] <= stats["deep_any"]["high"]
        )
        assert round(stats["break_even"], 4) == 0.5319
        patterns = (await rig.client.get(f"{API}/market/patterns")).json()["items"]
        assert [p["pattern"] for p in patterns] == [
            "alternating",
            "mixed",
            "tight",
            "overlap",
            "choppy",
        ]


async def test_a_scan_needs_prices_and_settings_that_fit(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        no_prices = await scan_body(rig)
        assert no_prices.status_code == 422
        assert no_prices.json()["error"]["code"] == "invalid_market"
        assert "download them on the Backtest page" in no_prices.json()["error"]["message"]
        await download(rig, START, END)
        misfit = await scan_body(rig, rules={"pattern": "mixed", "candles": 4, "misses": 3})
        assert misfit.json()["error"]["code"] == "invalid_market"
        assert (await scan_body(rig, rules={"candles": 1})).status_code == 422
        backwards = await scan_body(rig, start=END, end=START)
        assert "after the start" in backwards.json()["error"]["message"]
        too_long = await scan_body(rig, end="2023-12-31T00:00:00Z")
        assert "31 days" in too_long.json()["error"]["message"]
