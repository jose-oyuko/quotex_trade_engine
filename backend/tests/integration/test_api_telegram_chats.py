"""/api/v1/telegram/chats: the owner picks a group by name instead of typing its chat id."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.telegram.listener import ListenerState
from app.telegram.source import DialogInfo, DialogKind
from tests.api_support import ApiRig, running_api

URL = "/api/v1/telegram/chats"

DIALOGS = [
    DialogInfo(-1002, "zebra signals", DialogKind.CHANNEL),
    DialogInfo(-1001, "Alpha Signals", DialogKind.GROUP),
    DialogInfo(777, "Mum", DialogKind.USER),
    DialogInfo(-1003, "beta vip", DialogKind.GROUP),
]


async def ready(rig: ApiRig) -> None:
    rig.fakes.source.set_dialogs(DIALOGS)


async def test_it_lists_groups_and_channels_by_name_and_leaves_private_chats_out(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await ready(rig)
        response = await rig.client.get(URL)
    assert response.status_code == 200
    assert response.json()["items"] == [
        {"chat_id": -1001, "title": "Alpha Signals", "kind": "group", "added": False},
        {"chat_id": -1003, "title": "beta vip", "kind": "group", "added": False},
        {"chat_id": -1002, "title": "zebra signals", "kind": "channel", "added": False},
    ]  # alphabetical ignoring case; "Mum" is a person, not a signal source


async def test_chats_that_already_have_a_group_are_marked(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await ready(rig)
        await rig.create_group(telegram_chat_id=-1003, title="Beta")
        items = (await rig.client.get(URL)).json()["items"]
    assert {c["chat_id"]: c["added"] for c in items} == {-1001: False, -1003: True, -1002: False}


async def test_a_chat_without_a_name_is_shown_by_its_id(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        rig.fakes.source.set_dialogs([DialogInfo(-1009, "", DialogKind.GROUP)])
        items = (await rig.client.get(URL)).json()["items"]
    assert items[0]["title"] == "-1009"


async def test_without_the_engine_it_says_how_to_turn_it_on(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        response = await rig.client.get(URL)
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "engine_not_running" and "Settings page" in error["message"]


async def test_while_telegram_is_down_it_says_so(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await ready(rig)
        rig.fakes.source.lose_connection()

        async def down() -> bool:
            return rig.fakes.engine.listener.state is not ListenerState.CONNECTED

        await rig.eventually(down)
        response = await rig.client.get(URL)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "telegram_not_connected"


async def test_a_failure_inside_telegram_is_a_clean_error_without_its_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:

        async def broken() -> list[DialogInfo]:
            raise RuntimeError("secret-internal-detail")

        monkeypatch.setattr(rig.fakes.source, "list_dialogs", broken)
        response = await rig.client.get(URL)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "telegram_unavailable"
    assert "secret-internal-detail" not in response.text


async def test_a_telegram_that_never_answers_does_not_hang_the_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.engine.engine.CHAT_LIST_TIMEOUT_S", 0.05)
    async with running_api(tmp_path, with_engine=True) as rig:

        async def never() -> list[DialogInfo]:
            await asyncio.sleep(3600)
            return []

        monkeypatch.setattr(rig.fakes.source, "list_dialogs", never)
        async with asyncio.timeout(5):
            response = await rig.client.get(URL)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "telegram_unavailable"


async def test_listing_chats_changes_nothing(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await ready(rig)
        before = rig.fakes.source.chats
        await rig.client.get(URL)
        groups = (await rig.client.get("/api/v1/groups")).json()
    assert rig.fakes.source.chats == before and groups["total"] == 0
