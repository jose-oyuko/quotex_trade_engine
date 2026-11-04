"""Bodies of the settings and stored-secrets endpoints. No response here ever carries a secret."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SettingItemOut(BaseModel):
    key: str
    label: str
    help: str
    kind: Literal["choice", "text"]
    choices: list[str]
    value: str  # what the application will use at its next start
    default_value: str  # what it would use without a stored value
    source: Literal["database", "environment", "default"]


class SettingsOut(BaseModel):
    items: list[SettingItemOut]
    apply_note: str


class SettingsIn(BaseModel):
    """`null` for a key removes the stored value (back to `.env` or the default)."""

    values: dict[str, str | None] = Field(min_length=1, max_length=20)


class SecretItemOut(BaseModel):
    name: str
    label: str
    help: str
    group: Literal["logins", "telegram"]
    is_set: bool
    readable: bool  # False when SECRET_KEY is missing or is not the key it was stored with
    updated_at: datetime | None


class SecretsOut(BaseModel):
    key: Literal["ok", "missing", "invalid"]  # what SECRET_KEY in .env is like (never its value)
    items: list[SecretItemOut]


class SecretIn(BaseModel):
    value: str = Field(min_length=1, max_length=512)


class EnvLoginOut(BaseModel):
    label: str
    in_env: bool = Field(description="backend/.env still has a value for it.")
    stored: bool = Field(description="The encrypted store has one (it wins over .env).")


class EnvLoginsOut(BaseModel):
    items: list[EnvLoginOut]


class EnvImportOut(BaseModel):
    imported: list[str] = Field(description="The logins moved just now.")
    items: list[EnvLoginOut]
