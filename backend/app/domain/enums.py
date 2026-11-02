"""Enumerations shared by the engine, the database and (later) the API."""

from __future__ import annotations

from enum import StrEnum


class AccountType(StrEnum):
    DEMO = "demo"
    REAL = "real"


class Direction(StrEnum):
    CALL = "call"
    PUT = "put"


class Strategy(StrEnum):
    NO_MARTINGALE = "no_martingale"
    MARTINGALE = "martingale"
    FLIP_EVERY_LOSS = "flip_every_loss"
    TWO_STEP_FLIP = "two_step_flip"


class AssetSuffixMode(StrEnum):
    OTC = "otc"
    NONE = "none"
    AUTO = "auto"


class SignalStatus(StrEnum):
    PARSED = "parsed"
    NOT_PARSED = "not_parsed"
    IGNORED = "ignored"


class ChainStatus(StrEnum):
    PENDING = "pending"
    OPEN = "open"
    COMPLETED = "completed"
    EXHAUSTED = "exhausted"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TradeStatus(StrEnum):
    PENDING = "pending"
    OPEN = "open"
    WON = "won"
    LOST = "lost"
    DRAW = "draw"
    FAILED = "failed"
    UNKNOWN = "unknown"


# A chain/trade in one of these states still needs the engine's attention after a restart.
ACTIVE_CHAIN_STATUSES = frozenset({ChainStatus.PENDING, ChainStatus.OPEN})
UNSETTLED_TRADE_STATUSES = frozenset({TradeStatus.PENDING, TradeStatus.OPEN})
# A trade in one of these states has a known profit figure (win, loss or refunded draw).
RESULT_TRADE_STATUSES = frozenset({TradeStatus.WON, TradeStatus.LOST, TradeStatus.DRAW})
