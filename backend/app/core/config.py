"""Application settings, read from environment variables and an optional `.env` file."""

from __future__ import annotations

from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_NAMES = frozenset({"localhost"})


class PublicBindRefusedError(ValueError):
    """Raised when the server is asked to listen on a non-loopback address without opt-in."""


def is_loopback_host(host: str) -> bool:
    """True for `localhost` and loopback IP addresses (127.0.0.0/8, ::1)."""
    if host.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    """All configuration. Defaults are the safe ones: loopback bind, demo account."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    # The API can place trades and has no login, so a public bind must be a deliberate choice.
    allow_public_bind: bool = False

    environment: Literal["development", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    data_dir: Path = Path("data")

    # Used by the dev proxy; production serves the frontend from the same origin.
    cors_origin: str = "http://127.0.0.1:5173"

    @property
    def database_path(self) -> Path:
        return self.data_dir.resolve() / "quotex.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path.as_posix()}"

    @model_validator(mode="after")
    def _refuse_public_bind(self) -> Settings:
        if not self.allow_public_bind and not is_loopback_host(self.host):
            raise PublicBindRefusedError(
                f"Refusing to listen on {self.host!r}: the API can place trades and has no login. "
                "Use HOST=127.0.0.1, or set ALLOW_PUBLIC_BIND=true if you really mean it."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, built once."""
    return Settings()
