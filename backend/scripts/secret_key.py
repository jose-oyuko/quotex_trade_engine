"""Create the key that encrypts the logins stored in the dashboard.

    npm run key:create

Writes `SECRET_KEY=...` into `backend/.env` if there is no key yet (`npm start` does the same by
itself). It never replaces a key that is there: the stored secrets could not be read any more. The
key is not printed; it is in `backend/.env`. **Keep a copy of that file somewhere safe**: lose the
key and the stored logins are lost (you type them again); keep it next to a backup of the database
and the backup is as sensitive as the passwords.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.vault.key import ensure_secret_key

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def create(env_file: Path = ENV_FILE) -> str:
    """Do the work; returns what to tell the owner."""
    if ensure_secret_key(env_file):
        return (
            f"Created SECRET_KEY in {env_file}.\n"
            "Keep a copy of that file somewhere safe: without the key, the logins stored in the "
            "dashboard cannot be read again."
        )
    return (
        "SECRET_KEY is already set. Nothing was changed (replacing it would orphan stored logins)."
    )


def main(argv: list[str]) -> int:
    if argv:
        sys.stderr.write("This command takes no arguments.\n")
        return 2
    sys.stdout.write(create() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
