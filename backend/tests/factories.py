"""Builders for records, with sensible defaults. Override only what a test cares about."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.enums import (
    AccountType,
    AssetSuffixMode,
    ChainStatus,
    Direction,
    RepeatKind,
    RunState,
    SignalStatus,
    Strategy,
    TradeStatus,
)
from app.domain.ids import new_id
from app.domain.records import (
    BalanceSnapshotRecord,
    ChainRecord,
    GroupRecord,
    GroupSettingsRecord,
    RiskEventRecord,
    SessionRecord,
    SessionRunRecord,
    SignalRecord,
    TradeRecord,
)

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)


def make_group(**overrides: Any) -> GroupRecord:
    fields: dict[str, Any] = {
        "telegram_chat_id": -1001234567890,
        "title": "Signals A",
        "enabled": True,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return GroupRecord(**{**fields, **overrides})


def make_settings(group_id: int, **overrides: Any) -> GroupSettingsRecord:
    fields: dict[str, Any] = {
        "group_id": group_id,
        "parser": "legacy_v1",
        "asset_suffix_mode": AssetSuffixMode.OTC,
        "timezone": "UTC-3",
        "strategy": Strategy.FLIP_EVERY_LOSS,
        "base_stake": Decimal("1.00"),
        "max_steps": 3,
        "multipliers": (Decimal("2.0"), Decimal("2.5"), Decimal("3.0")),
        "min_payout_pct": 80,
        "updated_at": NOW,
    }
    return GroupSettingsRecord(**{**fields, **overrides})


def make_signal(group_id: int, **overrides: Any) -> SignalRecord:
    fields: dict[str, Any] = {
        "id": new_id(),
        "group_id": group_id,
        "telegram_message_id": 1,
        "received_at": NOW,
        "raw_text": "USD/JPY;12:05;CALL",
        "status": SignalStatus.PARSED,
        "asset": "USDJPY_otc",
        "direction": Direction.CALL,
        "duration_s": 60,
    }
    return SignalRecord(**{**fields, **overrides})


def make_chain(group_id: int, signal_id: UUID | None = None, **overrides: Any) -> ChainRecord:
    fields: dict[str, Any] = {
        "id": new_id(),
        "group_id": group_id,
        "signal_id": signal_id,
        "asset": "USDJPY_otc",
        "origin_direction": Direction.CALL,
        "duration_s": 60,
        "account_type": AccountType.DEMO,
        "strategy": Strategy.FLIP_EVERY_LOSS,
        "status": ChainStatus.OPEN,
        "step": 0,
        "consecutive_losses": 0,
        "max_steps": 3,
        "base_stake": Decimal("1.00"),
        "multipliers": (Decimal("2.0"), Decimal("2.5"), Decimal("3.0")),
        "created_at": NOW,
        "updated_at": NOW,
    }
    return ChainRecord(**{**fields, **overrides})


def make_trade(chain_id: UUID, group_id: int, **overrides: Any) -> TradeRecord:
    fields: dict[str, Any] = {
        "id": new_id(),
        "chain_id": chain_id,
        "group_id": group_id,
        "step": 0,
        "asset": "USDJPY_otc",
        "direction": Direction.CALL,
        "duration_s": 60,
        "stake": Decimal("1.00"),
        "account_type": AccountType.DEMO,
        "status": TradeStatus.OPEN,
        "created_at": NOW,
    }
    return TradeRecord(**{**fields, **overrides})


def make_risk_event(**overrides: Any) -> RiskEventRecord:
    fields: dict[str, Any] = {
        "id": new_id(),
        "occurred_at": NOW,
        "kind": "max_stake",
        "message": "stake 50.00 is above the limit 10.00",
    }
    return RiskEventRecord(**{**fields, **overrides})


def make_balance(**overrides: Any) -> BalanceSnapshotRecord:
    fields: dict[str, Any] = {
        "id": new_id(),
        "taken_at": NOW,
        "account_type": AccountType.DEMO,
        "balance": Decimal("10000.00"),
    }
    return BalanceSnapshotRecord(**{**fields, **overrides})


def make_session(**overrides: Any) -> SessionRecord:
    """A daily 11:00-12:00 UTC session on EURUSD with M5 trades (the group is 50)."""
    fields: dict[str, Any] = {
        "id": 1,
        "name": "Test session",
        "enabled": True,
        "group_id": 50,
        "asset": "EURUSD",
        "duration_s": 300,
        "start_time": time(11, 0),
        "end_time": time(12, 0),
        "timezone": "UTC",
        "repeat": RepeatKind.WEEKDAYS,
        "weekdays": (0, 1, 2, 3, 4, 5, 6),
        "pause_s": 0,
        "created_at": NOW,
        "updated_at": NOW,
        "once_after": NOW,
    }
    return SessionRecord(**{**fields, **overrides})


def make_session_run(session_id: int = 1, **overrides: Any) -> SessionRunRecord:
    fields: dict[str, Any] = {
        "id": new_id(),
        "session_id": session_id,
        "started_by": "schedule",
        "account_type": AccountType.DEMO,
        "started_at": NOW,
        "window_end": NOW + timedelta(hours=1),
        "state": RunState.RUNNING,
        "updated_at": NOW,
    }
    return SessionRunRecord(**{**fields, **overrides})
