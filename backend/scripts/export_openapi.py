"""Write the API's OpenAPI document to docs/openapi.json, the single source the frontend's types
are generated from.

    npm run api:export          write docs/openapi.json
    npm run api:export -- --check   fail if the committed file is out of date

The document is built from the code (routes, request/response models, WebSocket messages), so it
never needs editing by hand: run `npm run api:generate` after changing the API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.main import create_app

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def render() -> str:
    """The document as text: stable key order, so a diff shows only real changes."""
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            sys.stderr.write(f"{OUTPUT} is out of date: run `npm run api:export`.\n")
            return 1
        sys.stdout.write("docs/openapi.json is up to date.\n")
        return 0
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {OUTPUT}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
