"""Telegram chats the owner can pick a group from."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatOut(BaseModel):
    chat_id: int = Field(description="What a group's `telegram_chat_id` must be.")
    title: str
    kind: Literal["group", "channel"]
    added: bool = Field(description="A group for this chat already exists.")


class ChatsOut(BaseModel):
    items: list[ChatOut]
