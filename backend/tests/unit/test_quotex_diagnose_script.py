"""The live diagnostic script's own flow, driven with the fake adapter (no network, no account)."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.core.clock import SystemClock
from app.domain.enums import AccountType
from app.quotex import FakeQuotexAdapter

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "quotex_diagnose.py"


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("quotex_diagnose", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("QUOTEX_EMAIL", "secret-user@example.invalid")
    monkeypatch.setenv("QUOTEX_PASSWORD", "secret-password-123")
    return module


def args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "asset": "EURUSD",
        "order": False,
        "amount": "1.00",
        "duration": 60,
        "direction": "call",
    }
    return argparse.Namespace(**{**values, **overrides})


def use_fake(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[FakeQuotexAdapter]:
    built: list[FakeQuotexAdapter] = []

    def build(settings: Any, **kwargs: Any) -> FakeQuotexAdapter:
        assert kwargs["account_type"] is AccountType.DEMO  # the script must only ever ask for demo
        fake = FakeQuotexAdapter(clock=SystemClock())
        fake.add_asset("EURUSD", payout=86)
        built.append(fake)
        return fake

    monkeypatch.setattr(script, "build_pyquotex_adapter", build)
    return built


async def test_without_credentials_it_explains_and_exits(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("QUOTEX_EMAIL")
    monkeypatch.delenv("QUOTEX_PASSWORD")
    monkeypatch.chdir(Path(__file__).parent)  # a folder with no .env
    assert await script.run(args()) == 2
    assert "QUOTEX_EMAIL" in capsys.readouterr().out


async def test_read_only_run_shows_balance_and_payout_and_places_no_order(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    [*_] = built = use_fake(script, monkeypatch)
    assert await script.run(args()) == 0
    out = capsys.readouterr().out
    assert "demo balance: 1000.00" in out
    assert "payout EURUSD 1m: 86%" in out
    assert "no order placed" in out
    assert built[0].orders == []


async def test_order_run_places_exactly_one_demo_order_and_prints_the_result(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    built = use_fake(script, monkeypatch)
    assert await script.run(args(order=True, amount="2.00", direction="put")) == 0
    out = capsys.readouterr().out
    assert "confirmed" in out and "result: won, profit 1.72" in out
    assert "NEGATIVE profit" in out  # reminds the owner what to verify
    [order] = built[0].orders
    assert (order.account_type, str(order.amount), order.direction.value) == (
        AccountType.DEMO,
        "2.00",
        "put",
    )


async def test_a_closed_asset_is_not_ordered(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    built = use_fake(script, monkeypatch)
    assert await script.run(args(order=True, asset="XAUUSD")) == 1
    assert built[0].orders == []
    assert "closed" in capsys.readouterr().out


async def test_credentials_are_never_printed(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_fake(script, monkeypatch)
    await script.run(args(order=True))
    out = capsys.readouterr()
    assert "secret-password-123" not in out.out + out.err
    assert "secret-user@example.invalid" not in out.out + out.err


async def test_a_bad_amount_is_rejected_up_front(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake(script, monkeypatch)
    assert await script.run(args(amount="lots")) == 2


async def test_a_dns_failure_points_at_the_host_setting(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.quotex.errors import QuotexConnectionError

    built = use_fake(script, monkeypatch)
    original = script.build_pyquotex_adapter

    def failing(settings: Any, **kwargs: Any) -> FakeQuotexAdapter:
        fake = original(settings, **kwargs)
        fake.fail_next_connect(QuotexConnectionError("curl: (6) Could not resolve host: x.invalid"))
        return fake  # type: ignore[no-any-return]

    monkeypatch.setattr(script, "build_pyquotex_adapter", failing)
    assert await script.run(args()) == 1
    out = capsys.readouterr().out
    assert "does not resolve" in out and "QUOTEX_HOST" in out
    assert built[0].orders == []
