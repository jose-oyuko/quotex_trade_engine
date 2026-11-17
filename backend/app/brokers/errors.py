"""Errors raised by the broker adapters (Quotex and Deriv alike, decision D-74).

The split that matters to the engine is *did the order possibly reach the broker?*:
- `OrderRejectedError`, `AssetClosedError`, `NotConnectedError`, `AccountMismatchError`,
  `InvalidOrderError`: the order was certainly **not** placed.
- `OrderAckTimeoutError`: the order was sent but no confirmation arrived, so it **may** exist.
  The chain must be treated as `unknown`, never silently retried.

`app.quotex.errors` keeps the older names (`QuotexError`, `QuotexConnectionError`) for the same
classes.
"""

from __future__ import annotations

from app.core.errors import DomainError


class BrokerError(DomainError):
    """Base class for every adapter error."""


class BrokerConnectionError(BrokerError):
    """Could not connect, log in, or the connection was lost."""


class LoginRejectedError(BrokerConnectionError):
    """The broker refused the login itself (a wrong or revoked token, the wrong kind of account).
    Trying again cannot help, so the adapter stops retrying and says why."""


class NotConnectedError(BrokerConnectionError):
    """An operation needed a live connection and there is none."""


class InvalidOrderError(BrokerError, ValueError):
    """The order parameters are wrong (stake, duration, ...). Nothing was sent."""


class DurationNotOfferedError(InvalidOrderError):
    """The broker does not offer this trade length on this asset (decision D-77). Nothing was
    sent."""


class AssetClosedError(BrokerError):
    """The asset is unknown or currently closed. Nothing was sent."""


class AccountMismatchError(BrokerError):
    """The connection is on a different account (demo/real) than the adapter believes.
    Nothing was sent; this guards against trading on the wrong account."""


class RealAccountNotAllowedError(BrokerError):
    """Switching to the REAL account was requested but real trading is not enabled (D-15)."""


class OrderRejectedError(BrokerError):
    """The broker answered the order with an error. The order was not placed."""


class OrderAckTimeoutError(BrokerError):
    """The order was sent but the broker did not confirm it in time: it may have been placed."""

    may_have_been_placed = True


class ResultTimeoutError(BrokerError):
    """The result of an order did not arrive in time. The trade is still unresolved, not lost."""


class PayoutSanityError(BrokerError):
    """The broker's data does not look like what it is documented to deliver (wrong layout,
    payout outside 0-100). Fail loudly rather than trade on a wrong number (D-12)."""
