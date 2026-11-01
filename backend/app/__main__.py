"""`python -m app` starts the server on the configured (loopback by default) address."""

from __future__ import annotations

import sys

import uvicorn
from pydantic import ValidationError

from app.core.config import Settings


def main() -> int:
    try:
        settings = Settings()
    except ValidationError as exc:
        # Includes the "refusing public bind" message from the settings validator.
        sys.stderr.write(f"Invalid configuration:\n{exc}\n")
        return 2
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
