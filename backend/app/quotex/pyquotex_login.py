"""Logging in to Quotex from the dashboard, through pyquotex (decisions D-6, D-66).

The library keeps its login (cookies and a token) in a file called `session.json`, in a folder it is
told about. Here that folder is a private temporary one, made for this login and removed when it
ends, whatever the outcome; what the library wrote is read back as text for the application to keep
encrypted. So a login made on the dashboard never leaves a credential on disk.

Quotex sometimes e-mails a PIN to confirm a login from a new place. The library asks for it through
a callback; here that callback is `LoginRequest.ask_pin`, which the dashboard answers when the owner
has typed the PIN. Nothing here reads the console.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import structlog
from pyquotex import config as qx_config
from pyquotex.stable_api import Quotex

from app.quotex.base import LoginRequest
from app.quotex.errors import QuotexConnectionError
from app.quotex.pyquotex_client import explain_connect_error

log = structlog.get_logger()


class PyQuotexLogin:
    def __init__(self, request: LoginRequest, *, quotex_class: Any = Quotex) -> None:
        self._request = request
        self._quotex = quotex_class

    async def run(self) -> str:
        request = self._request
        folder = Path(tempfile.mkdtemp(prefix="qte-quotex-login-"))
        client: Any = None
        try:
            qx_config.base_dir = folder
            client = self._quotex(
                email=request.email,
                password=request.password,
                host=request.host,
                lang="en",
                root_path=str(folder),
                on_otp_callback=request.ask_pin,
            )
            client.set_account_mode("PRACTICE")  # logging in never needs the real account
            try:
                ok, reason = await client.connect()
            except (QuotexConnectionError, TimeoutError):
                raise
            except Exception as exc:
                raise QuotexConnectionError(explain_connect_error(exc)) from exc
            if not ok:
                raise QuotexConnectionError(f"Quotex did not accept the login: {reason}")
            session = _read_session(folder, request.email)
            if not session:
                raise QuotexConnectionError("Quotex accepted the login but gave no session.")
            return json.dumps(session)
        finally:
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    log.warning("quotex_login_close_failed", exc_info=True)
            shutil.rmtree(folder, ignore_errors=True)


def _read_session(folder: Path, email: str) -> dict[str, Any] | None:
    """The entry the library saved for `email`, if it holds a token."""
    try:
        everything = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = everything.get(email) if isinstance(everything, dict) else None
    return entry if isinstance(entry, dict) and entry.get("token") else None
