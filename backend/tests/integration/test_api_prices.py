"""/api/v1/prices: past prices for backtests (decision D-84), with the made-up price service."""

from __future__ import annotations

from pathlib import Path

from app.deriv.fake import FakePriceFeed, FakePriceHistory
from tests.api_support import ApiRig, running_api

API = "/api/v1"
START = "2023-11-14T00:00:00Z"


async def finished(rig: ApiRig, download_id: int) -> dict[str, object]:
    async def done() -> bool:
        items = (await rig.client.get(f"{API}/prices/downloads")).json()["items"]
        return any(d["id"] == download_id and d["state"] != "running" for d in items)

    await rig.eventually(done)
    items = (await rig.client.get(f"{API}/prices/downloads")).json()["items"]
    return next(d for d in items if d["id"] == download_id)


async def test_a_download_stores_prices_and_lists_them(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        assert (await rig.client.get(f"{API}/prices")).json() == {"items": [], "running": None}
        response = await rig.client.post(
            f"{API}/prices/downloads",
            json={"asset": "R_75", "start": START, "end": "2023-11-14T01:00:00Z"},
        )
        assert response.status_code == 202, response.text
        started = response.json()
        assert started["state"] == "running" and started["asset"] == "R_75"
        download = await finished(rig, started["id"])
        assert download["state"] == "done"
        assert download["progress"] == 1.0
        assert download["ticks"] == 1801  # a price every 2 s on an R_ index, both ends included
        prices = (await rig.client.get(f"{API}/prices")).json()
        [held] = prices["items"]
        assert held["asset"] == "R_75" and held["ticks"] == 1801
        assert held["ranges"] == [{"start": "2023-11-14T00:00:00Z", "end": "2023-11-14T01:00:00Z"}]
        assert prices["running"] is None

        assert (await rig.client.delete(f"{API}/prices/R_75")).status_code == 204
        assert (await rig.client.get(f"{API}/prices")).json()["items"] == []
        gone = await rig.client.delete(f"{API}/prices/R_75")
        assert gone.status_code == 404
        assert gone.json()["error"]["code"] == "download_not_found"


async def test_one_download_at_a_time_cancel_and_refusals(tmp_path: Path) -> None:
    slow = FakePriceHistory(FakePriceFeed())
    async with running_api(tmp_path, price_history=slow) as rig:
        rig.app.state.prices._pace_s = 30  # it waits after its first page
        first = await rig.client.post(
            f"{API}/prices/downloads",
            json={"asset": "1HZ75V", "start": START, "end": "2023-11-15T00:00:00Z"},
        )
        assert first.status_code == 202
        second = await rig.client.post(
            f"{API}/prices/downloads",
            json={"asset": "R_75", "start": START, "end": "2023-11-14T01:00:00Z"},
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "download_running"
        busy = await rig.client.delete(f"{API}/prices/1HZ75V")
        assert busy.json()["error"]["code"] == "asset_downloading"

        async def running_shown() -> bool:
            running = (await rig.client.get(f"{API}/prices")).json()["running"]
            return running is not None and running["ticks"] > 0

        await rig.eventually(running_shown)
        cancelled = await rig.client.post(f"{API}/prices/downloads/{first.json()['id']}/cancel")
        assert cancelled.status_code == 200
        body = cancelled.json()
        assert body["state"] == "cancelled" and body["ticks"] == 5000
        assert 0 < body["progress"] < 1

        too_long = await rig.client.post(
            f"{API}/prices/downloads",
            json={"asset": "R_75", "start": START, "end": "2023-12-31T00:00:00Z"},
        )
        assert too_long.status_code == 422
        assert too_long.json()["error"]["code"] == "invalid_download"
        bad_name = await rig.client.post(
            f"{API}/prices/downloads",
            json={"asset": "R 75; drop", "start": START, "end": "2023-11-14T01:00:00Z"},
        )
        assert bad_name.status_code == 422
        missing = await rig.client.post(f"{API}/prices/downloads/999/cancel")
        assert missing.status_code == 404
