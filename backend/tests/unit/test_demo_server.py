"""The demo (fake Quotex, fake Telegram): safe by construction, and it posts real signals."""

from __future__ import annotations

import ast
import asyncio
import random
from pathlib import Path

import httpx

from app.core.clock import SystemClock
from app.main import create_app
from app.quotex.fake import FakeQuotexAdapter
from app.signals.parsers.registry import ParserRegistry
from app.telegram import FakeTelegramSource
from scripts import demo_server
from scripts.demo_server import CHAT_TALK, GROUPS, DemoFeed, log_in_demo, seed_groups
from tests.api_support import BASE_URL, leave_engine_running, migrate, running_api, settings_for

FORBIDDEN_IMPORTS = (
    "app.quotex.pyquotex",
    "app.quotex.factory",
    "app.telegram.telethon_source",
    "app.telegram.factory",
    "app.engine.factory",
    "telethon",
    "pyquotex",
)


def test_the_demo_can_only_ever_use_the_simulators() -> None:
    """No import of the real Quotex adapter or Telegram wrapper, and the real `.env` is never read
    (so the owner's credentials cannot reach it)."""
    source = Path(demo_server.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert [m for m in imported if m.startswith(FORBIDDEN_IMPORTS)] == []
    assert "_env_file=None" in source


def test_the_feed_posts_real_signals_and_every_fifth_message_is_plain_chat() -> None:
    clock = SystemClock()
    adapter, source = FakeQuotexAdapter(clock=clock), FakeTelegramSource(clock)
    feed = DemoFeed(source, adapter, rng=random.Random(7))  # noqa: S311
    parser = ParserRegistry().get("legacy_v1")
    texts = [feed.emit_next() for _ in range(40)]
    assert feed.sent == 40
    chat = [t for t in texts if t in CHAT_TALK]
    signals = [t for t in texts if t not in CHAT_TALK]
    assert len(chat) == 8 and len(signals) == 32
    for text in signals:
        outcome = parser.parse(text)
        assert outcome.signal is not None, text  # the parser reads what the demo posts
        assert outcome.signal.base_asset in demo_server.ASSETS
        assert outcome.signal.duration_s == demo_server.EXPIRY_S
    for text in chat:
        assert parser.parse(text).signal is None


async def test_the_demo_groups_are_created_once_through_the_real_api(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        assert await seed_groups(rig.client) == len(GROUPS)
        assert await seed_groups(rig.client) == 0  # a second start keeps what is there
        groups = (await rig.client.get("/api/v1/groups")).json()["items"]
        assert [g["title"] for g in groups] == [g.title for g in GROUPS]
        assert {g["settings"]["strategy"] for g in groups} == {
            "martingale",
            "flip_every_loss",
            "no_martingale",
        }


async def test_the_feed_drives_the_real_engine_to_settled_trades(tmp_path: Path) -> None:
    """A whole application on the demo's own engine builder (result delay shortened for speed)."""
    holder: list[demo_server.Fakes] = []
    settings = settings_for(tmp_path)
    await migrate(settings)
    await leave_engine_running(settings)
    app = create_app(settings, engine_builder=demo_server.fake_builder(holder))
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client,
    ):
        await log_in_demo(app, client)
        await seed_groups(client)
        fakes = holder[0]
        assert await fakes.engine.listener.wait_until_connected(2)
        fakes.adapter.result_delay_s = 0.0
        feed = DemoFeed(fakes.source, fakes.adapter, win_rate=1.0, rng=random.Random(1))  # noqa: S311
        while not fakes.adapter.orders:
            feed.emit_next()
            await asyncio.sleep(0)
        await fakes.engine.manager.wait_idle(10)
        for _ in range(300):
            trades = (await client.get("/api/v1/trades")).json()["items"]
            if trades and all(t["status"] == "won" for t in trades):
                break
            await asyncio.sleep(0.02)
        assert trades
        assert all(t["status"] == "won" and t["account_type"] == "demo" for t in trades)
