"""Errors raised by the Quotex adapters.

The split that matters to the engine is *did the order possibly reach Quotex?*:
- `OrderRejectedError`, `AssetClosedError`, `NotConnectedError`, `AccountMismatchError`,
  `InvalidOrderError`: the order was certainly **not** placed.
- `OrderAckTimeoutError`: the order was sent but no confirmation arrived, so it **may** exist.
  The chain must be treated as `unknown`, never silently retried.
"""

from __future__ import annotations

from app.core.errors import DomainError


class QuotexError(DomainError):
    """Base class for every adapter error."""


class QuotexConnectionError(QuotexError):
    """Could not connect, log in, or the connection was lost."""


class NotConnectedError(QuotexConnectionError):
    """An operation needed a live connection and there is none."""


class InvalidOrderError(QuotexError, ValueError):
    """The order parameters are wrong (stake, duration, ...). Nothing was sent."""


class AssetClosedError(QuotexError):
    """The asset is unknown or currently closed. Nothing was sent."""


class AccountMismatchError(QuotexError):
    """The connection is on a different account (demo/real) than the adapter believes.
    Nothing was sent; this guards against trading on the wrong account."""


class RealAccountNotAllowedError(QuotexError):
    """Switching to the REAL account was requested but real trading is not enabled (D-15)."""


class OrderRejectedError(QuotexError):
    """Quotex answered the order with an error. The order was not placed."""


class OrderAckTimeoutError(QuotexError):
    """The order was sent but Quotex did not confirm it in time: it may have been placed."""

    may_have_been_placed = True


class ResultTimeoutError(QuotexError):
    """The result of an order did not arrive in time. The trade is still unresolved, not lost."""


class PayoutSanityError(QuotexError):
    """The instrument data does not look like what the library is documented to deliver
    (wrong layout, payout outside 0-100). Fail loudly rather than trade on a wrong number (D-12)."""
