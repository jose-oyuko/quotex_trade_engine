"""The fake broker under its Quotex name, and a fake of the dashboard's Quotex login."""

from __future__ import annotations

from app.brokers.fake import FakeBrokerAdapter, PlacedOrder
from app.quotex.base import LoginRequest
from app.quotex.errors import QuotexConnectionError, QuotexError

__all__ = ["FakeQuotexAdapter", "FakeQuotexLogin", "PlacedOrder"]


class FakeQuotexAdapter(FakeBrokerAdapter):
    """See `FakeBrokerAdapter`."""

    COMPONENT = "quotex"
    LABEL = "Quotex"


class FakeQuotexLogin:
    """Behaves like `QuotexLogin` for tests: no network, no library, scripted outcomes."""

    def __init__(
        self,
        request: LoginRequest,
        *,
        pin: str | None = None,
        pin_is_right: str = "123456",
        fail_with: QuotexError | None = None,
        session: str = '{"cookies": "c=1", "token": "fake-token", "user_agent": "test"}',
    ) -> None:
        self.request = request
        self.pin = pin  # when set, the login asks for a PIN first
        self.pin_is_right = pin_is_right
        self.fail_with = fail_with
        self.session = session
        self.pins_seen: list[str] = []
        self.ran = False

    async def run(self) -> str:
        self.ran = True
        if self.fail_with is not None:
            raise self.fail_with
        if self.pin is not None:
            answer = await self.request.ask_pin("Enter the PIN we just sent to your email: ")
            self.pins_seen.append(answer)
            if answer != self.pin_is_right:
                raise QuotexConnectionError(
                    "Quotex did not accept the login: Login failed. Wrong PIN"
                )
        return self.session
