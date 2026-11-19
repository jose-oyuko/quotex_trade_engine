"""`npm run deriv:check` driven against the local fake Deriv (no network, no account)."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.core.clock import SystemClock
from app.core.tasks import TaskSupervisor
from app.deriv import DerivAdapter
from app.domain.enums import AccountType
from tests.deriv_server import FakeDerivServer

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deriv_check.py"


@pytest.fixture
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deriv_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def server() -> AsyncIterator[FakeDerivServer]:
    deriv = FakeDerivServer()
    await deriv.start()
    yield deriv
    await deriv.stop()


def args(**overrides: Any) -> argparse.Namespace:
    values = {
        "asset": "R_75",
        "order": False,
        "amount": "1.00",
        "duration": 60,
        "direction": "call",
        "timeline": False,
        "count": 3,
    }
    return argparse.Namespace(**{**values, **overrides})


def use_server(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, server: FakeDerivServer
) -> None:
    def build(
        settings: Any, *, tasks: TaskSupervisor, clock: Any, account_type: AccountType
    ) -> Any:
        assert account_type is AccountType.DEMO  # the script must only ever ask for demo
        return DerivAdapter(
            server.link,
            tasks=tasks,
            clock=SystemClock(),
            ack_timeout_s=2.0,
            early_result=settings.deriv_early_result == "ON",
        )

    monkeypatch.setattr(script, "build_deriv_adapter", build)


async def test_without_logins_it_explains_and_exits(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(Path(__file__).parent)  # a folder with no .env
    for name in ("DERIV_APP_ID", "DERIV_TOKEN_DEMO"):
        monkeypatch.delenv(name, raising=False)
    assert await script.run(args()) == 2
    assert "DERIV_TOKEN_DEMO" in capsys.readouterr().out


async def test_a_read_only_run_shows_assets_lengths_and_payouts_and_trades_nothing(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    server: FakeDerivServer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_server(script, monkeypatch, server)
    assert await script.run(args()) == 0
    out = capsys.readouterr().out
    assert "demo balance: 10000.00 USD" in out
    assert "forex: AUDUSD (closed), EURUSD" in out and "synthetic_index: R_75" in out
    assert "Rise/Fall trade lengths: 15 min to 365 days" in out
    assert "Deriv says: CALL intraday from '15m' to '365d'" in out
    assert "payout EURUSD 15 min: 80%" in out and "payout R_75 1 min: 95%" in out
    assert "no trade placed" in out
    assert server.contracts == {}


async def test_with_order_it_places_one_demo_trade_and_reports_it(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    server: FakeDerivServer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_server(script, monkeypatch, server)
    server.profits.append(Decimal("-1.00"))
    assert await script.run(args(order=True)) == 0
    out = capsys.readouterr().out
    assert "result: lost, profit -1.00" in out
    assert len(server.contracts) == 1


async def test_a_length_deriv_does_not_offer_is_explained(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    server: FakeDerivServer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_server(script, monkeypatch, server)
    assert await script.run(args(order=True, asset="EURUSD", duration=60)) == 1
    out = capsys.readouterr().out
    assert "[FAILED] DurationNotOfferedError" in out and "15 min to 365 days" in out
    assert server.contracts == {}


def test_an_unreadable_offer_is_shown_as_deriv_sent_it(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.deriv_check import show_raw

    entry = {"contract_category": "rise_fall", "contract_type": "RISE", "min": "1m"}
    show_raw({"contracts_for": {"available": [entry, entry]}, "msg_type": "contracts_for"})
    out = capsys.readouterr().out
    assert "contracts_for has: ['available']" in out
    assert out.count("raw: contract_category='rise_fall'") == 1  # repeats shown once
    assert '"min": "1m"' in out
    show_raw({"contracts_for": None})
    assert "contracts_for is NoneType" in capsys.readouterr().out


async def test_the_timeline_times_the_early_result_against_deriv_s_own(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    server: FakeDerivServer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_server(script, monkeypatch, server)
    server.settle_after_s = None
    expiry = 1_800_000_060

    async def deriv_plays_the_contract() -> None:
        for _ in range(500):
            if server.contracts and server.sent("ticks"):
                break
            await asyncio.sleep(0.01)
        [contract_id] = server.contracts
        await server.set_terms(contract_id, entry=Decimal("100.00"), expiry=expiry)
        await server.push_tick("R_75", expiry - 1, Decimal("101.00"))
        await server.push_tick("R_75", expiry + 1, Decimal("100.50"))
        await asyncio.sleep(0.2)  # the engine knows; Deriv marks it sold a moment later
        await server.settle(contract_id, Decimal("0.95"))

    deriv = asyncio.ensure_future(deriv_plays_the_contract())
    assert await script.run(args(order=True, timeline=True, count=1)) == 0
    await deriv
    out = capsys.readouterr().out
    assert "tick of -1s: 101.0" in out
    assert "result used by the engine: profit 0.95" in out
    assert "Deriv's own result: 0.95 (agrees)" in out
    assert "early result = Deriv's own: 1 of 1" in out


def test_the_timeline_is_timed_from_the_end_time() -> None:
    from scripts.deriv_check import format_timeline

    expiry = 1000
    events = [
        (998.0, "contract", {"date_expiry": expiry, "status": "open", "is_sold": 0}),
        (999.4, "tick", (999, Decimal("2"))),
        (1001.3, "tick", (1001, Decimal("3"))),
        (1003.6, "contract", {"status": "won", "is_sold": 1, "profit": 0.95}),
    ]
    report = format_timeline(events, 1001.4, Decimal("0.95"))
    assert report.early_s is not None and round(report.early_s, 1) == 1.4
    assert report.sold_s is not None and round(report.sold_s, 1) == 3.6
    assert report.agrees
    assert "+1.30s  tick of +1s: 3" in report.text
    nothing = format_timeline([], 0.0, Decimal("1"))
    assert "no end time" in nothing.text and not nothing.agrees
