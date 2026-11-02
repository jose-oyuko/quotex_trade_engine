"""The chain state machine: the original signal trade plus its follow-ups.

    pending ──ack──► open ──win/draw──► completed
                      │ └──loss, more steps──► open (next step)
                      │ └──loss, no more steps──► exhausted
        any active ───┴──► stopped (owner) / failed (order refused) / unknown (outcome unclear)

A `Chain` is mutated only on the event loop and never awaits, so a read followed by a write cannot
be interleaved with another task (docs/ARCHITECTURE.md section 5). It knows nothing about Quotex:
the executor tells it what happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.core.errors import DomainError
from app.domain.enums import ACTIVE_CHAIN_STATUSES, AccountType, ChainStatus, Direction, Strategy
from app.domain.records import ChainRecord
from app.engine.strategies import StepPlan, has_follow_up, plan_step
from app.quotex.base import TradeOutcome


class InvalidTransitionError(DomainError):
    """Something happened to a chain that is already over, or in the wrong order."""


@dataclass(slots=True, frozen=True)
class ChainSpec:
    """Everything fixed when the chain is created. Group settings are copied in, so editing the
    group while the chain runs does not change it."""

    id: UUID
    group_id: int
    signal_id: UUID | None
    asset: str
    origin_direction: Direction
    duration_s: int
    account_type: AccountType
    strategy: Strategy
    base_stake: Decimal
    multipliers: tuple[Decimal, ...]
    max_steps: int


class Chain:
    def __init__(self, spec: ChainSpec, now: datetime) -> None:
        self.spec = spec
        self.status = ChainStatus.PENDING
        self.step = 0
        self.consecutive_losses = 0
        self.created_at = now
        self.updated_at = now
        self.ended_at: datetime | None = None
        self.end_reason: str | None = None

    @property
    def id(self) -> UUID:
        return self.spec.id

    @property
    def group_id(self) -> int:
        return self.spec.group_id

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_CHAIN_STATUSES

    def plan(self) -> StepPlan:
        """What to trade at the current step."""
        s = self.spec
        return plan_step(s.strategy, self.step, s.origin_direction, s.base_stake, s.multipliers)

    def mark_open(self, now: datetime) -> None:
        """The first order was confirmed by Quotex."""
        self._require_active()
        self.status = ChainStatus.OPEN
        self.updated_at = now

    def apply_result(self, outcome: TradeOutcome, now: datetime) -> StepPlan | None:
        """Record how the current trade ended. Returns the next step to place, or None when the
        chain is over (its status and reason are then set)."""
        self._require_active()
        self.updated_at = now
        if outcome is TradeOutcome.WON:
            self._end(ChainStatus.COMPLETED, f"won at step {self.step}", now)
            return None
        if outcome is TradeOutcome.DRAW:
            # Quotex refunds a draw: nothing was lost, so there is nothing to recover.
            self._end(ChainStatus.COMPLETED, f"draw at step {self.step} (stake refunded)", now)
            return None
        self.consecutive_losses += 1
        s = self.spec
        if not has_follow_up(s.strategy, self.step, s.max_steps):
            self._end(ChainStatus.EXHAUSTED, f"all {self.step + 1} trade(s) lost", now)
            return None
        self.step += 1
        self.status = ChainStatus.OPEN
        return self.plan()

    def fail(self, reason: str, now: datetime) -> None:
        """An order was refused (nothing reached Quotex)."""
        self._end_active(ChainStatus.FAILED, reason, now)

    def mark_unknown(self, reason: str, now: datetime) -> None:
        """An order may exist or its result is missing: never retried, shown to the owner."""
        self._end_active(ChainStatus.UNKNOWN, reason, now)

    def stop(self, reason: str, now: datetime) -> None:
        """Ended by the owner."""
        self._end_active(ChainStatus.STOPPED, reason, now)

    def to_record(self) -> ChainRecord:
        s = self.spec
        return ChainRecord(
            id=s.id,
            group_id=s.group_id,
            signal_id=s.signal_id,
            asset=s.asset,
            origin_direction=s.origin_direction,
            duration_s=s.duration_s,
            account_type=s.account_type,
            strategy=s.strategy,
            status=self.status,
            step=self.step,
            consecutive_losses=self.consecutive_losses,
            max_steps=s.max_steps,
            base_stake=s.base_stake,
            multipliers=s.multipliers,
            created_at=self.created_at,
            updated_at=self.updated_at,
            ended_at=self.ended_at,
            end_reason=self.end_reason,
        )

    # --- internals ---

    def _require_active(self) -> None:
        if not self.active:
            raise InvalidTransitionError(f"chain {self.id} is already {self.status.value}")

    def _end_active(self, status: ChainStatus, reason: str, now: datetime) -> None:
        self._require_active()
        self._end(status, reason, now)

    def _end(self, status: ChainStatus, reason: str, now: datetime) -> None:
        self.status = status
        self.end_reason = reason
        self.ended_at = now
        self.updated_at = now
