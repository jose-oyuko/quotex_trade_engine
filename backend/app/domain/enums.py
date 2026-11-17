"""Enumerations shared by the engine, the database and (later) the API."""

from __future__ import annotations

from enum import StrEnum


class AccountType(StrEnum):
    DEMO = "demo"
    REAL = "real"


class Broker(StrEnum):
    """Where a trade is placed (decision D-75). Groups and sessions choose one from Phase 20."""

    QUOTEX = "quotex"
    DERIV = "deriv"

    @property
    def label(self) -> str:
        """The name the owner reads: "Quotex", "Deriv"."""
        return self.value.capitalize()


class UserRole(StrEnum):
    ADMIN = "admin"  # the owner; invited users (a later phase) get their own roles


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


class GroupSource(StrEnum):
    """Where a group's trades come from: a Telegram chat, or the hidden group of a trading
    session (decision D-71)."""

    TELEGRAM = "telegram"
    SESSION = "session"


class RepeatKind(StrEnum):
    ONCE = "once"  # the next window only, never again
    WEEKDAYS = "weekdays"  # on the chosen days of the week


class SessionMode(StrEnum):
    SEQUENTIAL = "sequential"  # one pair at a time; the next after both chains ended (and a pause)
    EVERY_CANDLE = "every_candle"  # a pair at every candle, up to a number of open pairs


class RunState(StrEnum):
    RUNNING = "running"  # opening pairs
    STOPPING = "stopping"  # no more pairs; the chains already running finish (decision D-72)
    ENDED = "ended"


class RunEndReason(StrEnum):
    WINDOW_ENDED = "window_ended"
    PROFIT_TARGET = "profit_target"
    LOSS_LIMIT = "loss_limit"
    MAX_PAIRS = "max_pairs"
    STOPPED = "stopped"  # the owner pressed Stop
    KILL_SWITCH = "kill_switch"
    ENGINE_STOPPED = "engine_stopped"
    INTERRUPTED = "interrupted"  # the application stopped while it ran (decision D-35)
    ERROR = "error"


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
