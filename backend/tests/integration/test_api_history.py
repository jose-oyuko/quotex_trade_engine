"""/api/v1 chains, trades, signals and risk events: lists with filters and pages, and details."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.quotex.base import TradeOutcome
from tests.api_support import ApiRig, running_api

API = "/api/v1"


async def run_one_chain(rig: ApiRig) -> None:
    """A martingale chain that loses once, then wins: two trades, one chain, ends `completed`."""
    await rig.create_group()
    rig.fakes.adapter.script_results(TradeOutcome.LOST, TradeOutcome.WON)
    rig.fakes.signal(-1001, "EURUSD CALL 1m")
    rig.fakes.signal(-1001, "this is just chat, not a signal")
    await rig.fakes.engine.manager.wait_idle(5)

    async def stored() -> bool:
        chains = (await rig.client.get(f"{API}/chains")).json()["items"]
        trades = (await rig.client.get(f"{API}/trades")).json()["total"]
        signals = (await rig.client.get(f"{API}/signals")).json()["total"]
        return bool(chains) and chains[0]["status"] == "completed" and trades == 2 and signals == 2

    await rig.eventually(stored)


async def test_chains_can_be_listed_filtered_and_paged(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await run_one_chain(rig)
        page = (await rig.client.get(f"{API}/chains")).json()
        assert page["total"] == 1 and page["limit"] == 50 and page["offset"] == 0
        [chain] = page["items"]
        assert chain["asset"] == "EURUSD" and chain["strategy"] == "martingale"
        assert chain["status"] == "completed" and chain["account_type"] == "demo"
        assert chain["base_stake"] == "1.00" and chain["multipliers"] == ["2.0", "2.5"]

        for query, expected in [
            ({"status": "completed"}, 1),
            ({"status": "open"}, 0),
            ({"group_id": 1}, 1),
            ({"group_id": 2}, 0),
            ({"account_type": "demo"}, 1),
            ({"account_type": "real"}, 0),
        ]:
            got = (await rig.client.get(f"{API}/chains", params=query)).json()["total"]
            assert got == expected, query
        assert (await rig.client.get(f"{API}/chains", params={"status": "nope"})).status_code == 422
        empty = (await rig.client.get(f"{API}/chains", params={"offset": 5})).json()
        assert empty["items"] == [] and empty["total"] == 1


async def test_a_chain_detail_has_its_trades_in_order_and_the_message_that_started_it(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await run_one_chain(rig)
        chain_id = (await rig.client.get(f"{API}/chains")).json()["items"][0]["id"]
        detail = (await rig.client.get(f"{API}/chains/{chain_id}")).json()
        assert detail["chain"]["id"] == chain_id
        first, second = detail["trades"]
        assert (first["step"], first["status"], first["direction"]) == (0, "lost", "call")
        assert (second["step"], second["status"], second["direction"]) == (1, "won", "call")
        assert first["stake"] == "1.00" and second["stake"] == "2.00"
        assert first["profit"] is not None and second["profit"] is not None
        assert detail["signal"]["raw_text"] == "EURUSD CALL 1m"
        assert detail["signal"]["status"] == "parsed"

        # the first trade is timed from the message; a follow-up only from its own decision
        assert first["latency"]["signal_to_order_ms"] is not None
        assert first["latency"]["signal_to_order_ms"] >= first["latency"]["decision_to_order_ms"]
        assert second["latency"]["signal_to_order_ms"] is None
        assert second["latency"]["decision_to_order_ms"] is not None
        assert second["latency"]["order_ack_ms"] is not None


async def test_an_unknown_or_malformed_chain_id_is_refused(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        missing = await rig.client.get(f"{API}/chains/{uuid4()}")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "chain_not_found"
        assert (await rig.client.get(f"{API}/chains/not-a-uuid")).status_code == 422


async def test_trades_can_be_listed_filtered_paged_and_read_one_by_one(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await run_one_chain(rig)
        page = (await rig.client.get(f"{API}/trades")).json()
        assert page["total"] == 2
        assert {t["step"] for t in page["items"]} == {0, 1}

        for query, expected in [
            ({"status": "lost"}, 1),
            ({"status": "won"}, 1),
            ({"status": "open"}, 0),
            ({"group_id": 1}, 2),
            ({"group_id": 9}, 0),
            ({"account_type": "real"}, 0),
        ]:
            got = (await rig.client.get(f"{API}/trades", params=query)).json()["total"]
            assert got == expected, query

        first = (await rig.client.get(f"{API}/trades", params={"limit": 1})).json()
        second = (await rig.client.get(f"{API}/trades", params={"limit": 1, "offset": 1})).json()
        assert first["total"] == second["total"] == 2
        assert first["items"][0]["id"] != second["items"][0]["id"]

        one = (await rig.client.get(f"{API}/trades/{page['items'][0]['id']}")).json()
        assert one == page["items"][0]
        assert (await rig.client.get(f"{API}/trades/{uuid4()}")).status_code == 404
        assert (await rig.client.get(f"{API}/trades/xyz")).status_code == 422


async def test_every_message_is_in_the_signal_inbox_with_what_became_of_it(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await run_one_chain(rig)
        page = (await rig.client.get(f"{API}/signals")).json()
        by_text = {s["raw_text"]: s for s in page["items"]}
        assert by_text["EURUSD CALL 1m"]["status"] == "parsed"
        assert by_text["EURUSD CALL 1m"]["asset"] == "EURUSD"
        assert by_text["EURUSD CALL 1m"]["duration_s"] == 60
        assert by_text["this is just chat, not a signal"]["status"] == "not_parsed"
        assert by_text["this is just chat, not a signal"]["reason"]

        assert (await rig.client.get(f"{API}/signals", params={"status": "parsed"})).json()[
            "total"
        ] == 1
        assert (await rig.client.get(f"{API}/signals", params={"status": "ignored"})).json()[
            "total"
        ] == 0
        assert (await rig.client.get(f"{API}/signals", params={"group_id": 7})).json()["total"] == 0
        signal_id = by_text["EURUSD CALL 1m"]["id"]
        assert (await rig.client.get(f"{API}/signals/{signal_id}")).json() == by_text[
            "EURUSD CALL 1m"
        ]
        assert (await rig.client.get(f"{API}/signals/{uuid4()}")).status_code == 404


async def test_untrusted_message_text_comes_back_as_plain_json_text(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await rig.create_group()
        hostile = "<script>alert(1)</script> '; DROP TABLE signals; --"
        rig.fakes.signal(-1001, hostile)

        async def stored() -> bool:
            return (await rig.client.get(f"{API}/signals")).json()["total"] == 1

        await rig.eventually(stored)
        response = await rig.client.get(f"{API}/signals")
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["items"][0]["raw_text"] == hostile
        assert (await rig.client.get(f"{API}/signals")).json()["total"] == 1  # the table is fine
