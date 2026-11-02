"""Serves the built dashboard (`frontend/dist`) from the same process and port as the API, so in
production there is one address and no CORS (docs/ARCHITECTURE.md section 8).

Any path that is not a real file and does not look like a file request (`/groups`, `/history`...)
gets `index.html`, because the dashboard does its own routing in the browser. The API and the
WebSocket are never answered with a page: an unknown `/api/...` stays a JSON 404.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

log = structlog.get_logger()

NO_CACHE = {"Cache-Control": "no-cache"}


def mount_frontend(app: FastAPI, directory: Path) -> bool:
    """Serve `directory` if it holds a built dashboard. Returns whether anything was mounted."""
    root = directory.resolve()
    index = root / "index.html"
    if not index.is_file():
        log.info("frontend_not_built", directory=str(root), hint="run `npm run build`")
        return False

    async def dashboard(path: str) -> FileResponse:
        if path == "api" or path.startswith(("api/", "ws")):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            # built files carry a hash in their name, so they can be cached for good
            headers = {"Cache-Control": "public, max-age=31536000, immutable"}
            return FileResponse(candidate, headers=headers if "assets/" in path else NO_CACHE)
        if "." in path.rsplit("/", 1)[-1]:
            raise HTTPException(status_code=404)  # a missing file is not a page
        return FileResponse(index, headers=NO_CACHE)

    app.add_api_route("/{path:path}", dashboard, methods=["GET"], include_in_schema=False)
    return True
