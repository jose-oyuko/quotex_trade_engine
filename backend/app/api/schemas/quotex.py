"""Bodies of the Quotex login endpoints. No response here carries a password or a session."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QuotexLoginOut(BaseModel):
    state: Literal["logged_out", "working", "pin_needed", "logged_in"]
    configured: bool = Field(
        description="An email and a password are stored, so a login can begin."
    )
    pin_prompt: str | None = Field(description="What Quotex asks for, in its own words.")
    message: str | None = Field(description="Why the last login did not work, in words.")
    engine_running: bool = Field(description="Logging in or out needs the engine stopped.")


class PinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: str = Field(min_length=1, max_length=20, description="The digits Quotex e-mailed.")
