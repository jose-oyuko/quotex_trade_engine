"""Telegram chats the owner can pick a group from."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatOut(BaseModel):
    chat_id: int = Field(description="What a group's `telegram_chat_id` must be.")
    title: str
    kind: Literal["group", "channel"]
    added: bool = Field(description="A group for this chat already exists.")


class ChatsOut(BaseModel):
    items: list[ChatOut]


class LoginStatusOut(BaseModel):
    """Where the Telegram login is. Never the login itself."""

    state: Literal["logged_out", "code_sent", "password_needed", "logged_in"]
    configured: bool = Field(description="The API id and hash are stored, so a login can begin.")
    phone_hint: str | None = Field(description="The phone number with its middle hidden.")
    delivery: str | None = Field(description="Where Telegram says it sent the code, in words.")
    resends_left: int = Field(description="How many more times the code can be sent another way.")
    problem: str | None = Field(description="Why a stored login cannot be used.")
    engine_running: bool = Field(description="Logging in or out needs the engine stopped.")


class PhoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=40, description="International format.")


class CodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=20)


class TelegramPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256, description="Two-step verification.")
