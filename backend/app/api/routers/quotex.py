"""Logging in to Quotex from the dashboard, with the e-mailed PIN when Quotex asks (D-66)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import QuotexLoginDep
from app.api.schemas.quotex import PinIn, QuotexLoginOut
from app.services.quotex_login import QuotexLoginStatus

router = APIRouter(prefix="/quotex", tags=["quotex"])


def _out(status: QuotexLoginStatus) -> QuotexLoginOut:
    return QuotexLoginOut(
        state=status.state.value,
        configured=status.configured,
        pin_prompt=status.pin_prompt,
        message=status.message,
        engine_running=status.engine_running,
    )


@router.get("/login", response_model=QuotexLoginOut)
async def login_status(login: QuotexLoginDep) -> QuotexLoginOut:
    """Where the Quotex login is: logged out, talking to Quotex, waiting for the PIN, or logged in.
    Safe after a page reload."""
    return _out(await login.status())


@router.post("/login/start", response_model=QuotexLoginOut)
async def login_start(login: QuotexLoginDep) -> QuotexLoginOut:
    """Log in with the stored email and password. If Quotex e-mails a PIN, the answer says
    `pin_needed`. Needs the engine stopped. A refused login is not an error here: it comes back as
    `logged_out` with the reason in `message`."""
    return _out(await login.start())


@router.post("/login/pin", response_model=QuotexLoginOut)
async def login_pin(body: PinIn, login: QuotexLoginDep) -> QuotexLoginOut:
    """The PIN Quotex e-mailed. The login carries on and the answer says how it ended."""
    return _out(await login.submit_pin(body.pin))


@router.post("/login/cancel", response_model=QuotexLoginOut)
async def login_cancel(login: QuotexLoginDep) -> QuotexLoginOut:
    """Drop a login that is in progress."""
    return _out(await login.cancel())


@router.post("/logout", response_model=QuotexLoginOut)
async def logout(login: QuotexLoginDep) -> QuotexLoginOut:
    """Forget the stored Quotex login (the engine then logs in with the password). Needs the
    engine stopped."""
    return _out(await login.log_out())
