"""The owner's Telegram chats, so a group can be picked from a list instead of typing its id."""

from __future__ import annotations

import structlog
from fastapi import APIRouter

from app.api.deps import GroupsDep, RunningEngineDep
from app.api.errors import ApiError
from app.api.schemas.telegram import ChatOut, ChatsOut
from app.engine.errors import TelegramNotConnectedError

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
