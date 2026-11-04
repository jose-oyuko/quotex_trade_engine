"""Creating `SECRET_KEY` in `backend/.env` without ever overwriting a key that is there.

The key is what makes the stored secrets readable: replacing it would orphan them. So this only adds
a key when there is none (no line, or a blank one), keeps every other line as it was, and says so.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from app.vault.crypto import generate_key

_ACTIVE_LINE = re.compile(r"^\s*SECRET_KEY\s*=(.*)$")


def key_in_env_file(text: str) -> str | None:
    """The value of the last active `SECRET_KEY=` line, or None if there is none or it is blank."""
    value: str | None = None
    for line in text.splitlines():
        match = _ACTIVE_LINE.match(line)
        if match:
            value = match.group(1).strip().strip("\"'") or None
    return value


def ensure_secret_key(env_file: Path) -> bool:
    """Make sure `env_file` defines a key (creating the file if needed). Returns True if one was
    added. An existing key, and the `SECRET_KEY` environment variable, are left alone."""
    if os.environ.get("SECRET_KEY", "").strip():
        return False
    # bytes in and out: reading as text would turn Windows line endings into plain ones
    text = env_file.read_bytes().decode("utf-8") if env_file.is_file() else ""
    if key_in_env_file(text) is not None:
        return False
    eol = "\r\n" if "\r\n" in text else "\n"
    new_line = f"SECRET_KEY={generate_key()}"
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _ACTIVE_LINE.match(line)
        if match and not match.group(1).strip().strip("\"'"):
            lines[index] = new_line  # a blank `SECRET_KEY=` is filled in place
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Encrypts the logins stored in the dashboard. Keep a copy somewhere safe:")
        lines.append("# without this key they cannot be read again.")
        lines.append(new_line)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_bytes((eol.join(lines) + eol).encode("utf-8"))
    return True
