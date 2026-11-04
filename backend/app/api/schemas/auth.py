"""Request and response bodies of the login endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.enums import UserRole

# Generous upper bounds only: the real rules (and their friendly messages) are in the service. The
# limits keep a huge body from reaching the password hashing.
Username = Field(min_length=1, max_length=64)
Password = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    username: str
    role: UserRole


class AuthStateOut(BaseModel):
    """What the dashboard needs to decide which page to show first."""

    setup_required: bool
    authenticated: bool
    user: UserOut | None = None


class SetupIn(BaseModel):
    setup_code: str = Field(min_length=1, max_length=64)
    username: str = Username
    password: str = Password


class LoginIn(BaseModel):
    username: str = Username
    password: str = Password


class PasswordChangeIn(BaseModel):
    current_password: str = Password
    new_password: str = Password
