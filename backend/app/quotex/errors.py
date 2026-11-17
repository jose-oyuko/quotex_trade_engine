"""Errors raised by the Quotex adapters: the broker errors of `app.brokers.errors`, under the names
the Quotex code has always used (`QuotexError` is `BrokerError`, and so on)."""

from __future__ import annotations

from app.brokers.errors import (
    AccountMismatchError,
    AssetClosedError,
    BrokerConnectionError,
    BrokerError,
    InvalidOrderError,
    NotConnectedError,
    OrderAckTimeoutError,
    OrderRejectedError,
    PayoutSanityError,
    RealAccountNotAllowedError,
    ResultTimeoutError,
)

QuotexError = BrokerError
QuotexConnectionError = BrokerConnectionError

__all__ = [
    "AccountMismatchError",
    "AssetClosedError",
    "InvalidOrderError",
    "NotConnectedError",
    "OrderAckTimeoutError",
    "OrderRejectedError",
    "PayoutSanityError",
    "QuotexConnectionError",
    "QuotexError",
    "RealAccountNotAllowedError",
    "ResultTimeoutError",
]
