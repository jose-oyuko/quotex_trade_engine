"""Application settings, read from environment variables and an optional `.env` file."""

from __future__ import annotations

from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
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
    # The API can place trades. It has a login (decision D-59), but a login alone is not enough on
    # an open network (no HTTPS), so a public bind must still be a deliberate choice.
    allow_public_bind: bool = False

    environment: Literal["development", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    data_dir: Path = Path("data")
    # Logs also go to a rotating JSON file (decision D-50); the console shows them as before.
    log_to_file: bool = True
    log_max_mb: int = 10
    log_backups: int = 5

    # Used by the dev proxy; production serves the frontend from the same origin.
    cors_origin: str = "http://127.0.0.1:5173"

    # The API: commands (anything that changes something) are rate limited, and every dashboard on
    # the WebSocket gets its own bounded queue (a slow one loses its queue, never slows the engine).
    api_command_rate_per_s: float = 10.0
    api_command_burst: int = 40
    ws_client_queue: int = 1000
    ws_heartbeat_s: float = 15.0

    # The built dashboard (`npm run build`), served by the backend when it exists.
    frontend_dir: Path = Path("../frontend/dist")

    # Starts the trading engine (Quotex + Telegram + chains) with the application. Off by default:
    # starting the backend must never log in to Quotex or Telegram by surprise.
    engine_enabled: bool = False

    # Quotex. Credentials are secrets: SecretStr never shows up in logs or repr().
    quotex_email: SecretStr | None = None
    quotex_password: SecretStr | None = None
    # The broker's domain changes from time to time (the old qxbroker.com stopped resolving).
    quotex_host: str = "quotex.com"
    # Real-money trading must be switched on explicitly (decision D-15).
    quotex_allow_real: bool = False
    # TIME = expire at the next clock-aligned expiry, TIMER = a countdown of the given length.
    quotex_time_mode: Literal["TIME", "TIMER"] = "TIME"

    # Telegram. api_id/api_hash come from https://my.telegram.org (API development tools); the login
    # code and any 2FA password are typed into `npm run telegram:login` and never stored here.
    telegram_api_id: int | None = None
    telegram_api_hash: SecretStr | None = None
    telegram_phone: str | None = None  # international format, +<country code><number>

    @field_validator("telegram_api_id", "telegram_phone", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """A copied `.env` line like `TELEGRAM_API_ID=` means "not set", not an invalid number."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("quotex_host")
    @classmethod
    def _bare_hostname(cls, value: str) -> str:
        host = value.strip().lower()
        if not host or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in host):
            raise ValueError("QUOTEX_HOST must be a bare domain name such as quotex.com")
        return host

    @property
    def telegram_session_path(self) -> Path:
        """Telethon appends `.session`; the file holds a login, so it lives in git-ignored data/."""
        return self.data_dir.resolve() / "telegram"

    @property
    def log_path(self) -> Path:
        return self.data_dir.resolve() / "logs" / "engine.log"

    def secret_values(self) -> list[str]:
        """The values that must never appear in a log line."""
        secrets = (self.quotex_password, self.telegram_api_hash)
        return [s.get_secret_value() for s in secrets if s is not None]

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
                f"Refusing to listen on {self.host!r}: the API can place trades and is meant for "
                "loopback. Use HOST=127.0.0.1, or set ALLOW_PUBLIC_BIND=true if you really mean it."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, built once."""
    return Settings()
