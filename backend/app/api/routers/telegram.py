"""The owner's Telegram chats, so a group can be picked from a list instead of typing its id."""

from __future__ import annotations

import structlog
from fastapi import APIRouter

from app.api.deps import GroupsDep, RunningEngineDep, TelegramLoginDep
from app.api.errors import ApiError
from app.api.schemas.telegram import (
    ChatOut,
    ChatsOut,
    CodeIn,
    LoginStatusOut,
    PhoneIn,
    TelegramPasswordIn,
)
from app.engine.errors import TelegramNotConnectedError
from app.services.telegram_login import LoginStatus

log = structlog.get_logger()

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.get("/chats", response_model=ChatsOut)
async def list_chats(engine: RunningEngineDep, groups: GroupsDep) -> ChatsOut:
    """Groups and channels the logged-in Telegram account is in, by name, marking the ones that
    already have a group here. Needs the engine running (it owns the Telegram connection) and
    Telegram connected. Private chats are left out: signals come from groups and channels."""
    try:
        dialogs = await engine.list_chats()
    except TelegramNotConnectedError as exc:
        raise ApiError(
            503,
            "telegram_not_connected",
            "Telegram is not connected yet. Wait a moment, or run `npm run telegram:login` "
            "if it was never logged in.",
        ) from exc
    except Exception as exc:  # a timeout or whatever Telegram says: the list is just unavailable
        log.warning("telegram_chat_list_failed", error=f"{type(exc).__name__}: {exc}")
        raise ApiError(
            503,
            "telegram_unavailable",
            "Could not get the list of chats from Telegram. Try again in a moment.",
        ) from exc
    taken = {view.group.telegram_chat_id for view in await groups.list()}
    items = [
        ChatOut(
            chat_id=d.chat_id,
            title=d.title or str(d.chat_id),
            kind=d.kind,
            added=d.chat_id in taken,
        )
        for d in dialogs
    ]
    items.sort(key=lambda chat: chat.title.casefold())
    return ChatsOut(items=items)


# --- logging in to Telegram from the dashboard (decision D-65) ---


def _status_out(status: LoginStatus) -> LoginStatusOut:
    return LoginStatusOut(
        state=status.state.value,
        configured=status.configured,
        phone_hint=status.phone_hint,
        delivery=status.delivery,
        resends_left=status.resends_left,
        problem=status.problem,
        engine_running=status.engine_running,
    )


@router.get("/login", response_model=LoginStatusOut)
async def login_status(login: TelegramLoginDep) -> LoginStatusOut:
    """Where the Telegram login is: logged out, waiting for the code, waiting for the two-step
    password, or logged in. Safe to call after a page reload: a half-made login is still here."""
    return _status_out(await login.status())


@router.post("/login/start", response_model=LoginStatusOut)
async def login_start(body: PhoneIn, login: TelegramLoginDep) -> LoginStatusOut:
    """Step 1: Telegram sends a code to this number. Needs the API id and hash stored first, and
    the engine stopped."""
    return _status_out(await login.start(body.phone))


@router.post("/login/resend", response_model=LoginStatusOut)
async def login_resend(login: TelegramLoginDep) -> LoginStatusOut:
    """Ask Telegram to send the same code another way (SMS, a call)."""
    return _status_out(await login.resend())


@router.post("/login/code", response_model=LoginStatusOut)
async def login_code(body: CodeIn, login: TelegramLoginDep) -> LoginStatusOut:
    """Step 2: the code. The answer says if a password is needed next, or the login is done."""
    return _status_out(await login.submit_code(body.code))


@router.post("/login/password", response_model=LoginStatusOut)
async def login_password(body: TelegramPasswordIn, login: TelegramLoginDep) -> LoginStatusOut:
    """Step 3, only for an account with two-step verification."""
    return _status_out(await login.submit_password(body.password))


@router.post("/login/cancel", response_model=LoginStatusOut)
async def login_cancel(login: TelegramLoginDep) -> LoginStatusOut:
    """Drop a login that is half made."""
    return _status_out(await login.cancel())


@router.post("/logout", response_model=LoginStatusOut)
async def logout(login: TelegramLoginDep) -> LoginStatusOut:
    """Forget the Telegram login (and end it on Telegram's side if it can be reached). Needs the
    engine stopped."""
    return _status_out(await login.log_out())
