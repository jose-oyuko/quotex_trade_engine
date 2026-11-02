"""The built dashboard is served by the backend, without ever hiding the API."""

from __future__ import annotations

from pathlib import Path

import httpx

from app.main import create_app
from tests.api_support import BASE_URL, running_api, settings_for


def build_dist(root: Path) -> Path:
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>dash</title>", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (root / "secret.txt").write_text("do not serve", encoding="utf-8")
    return dist


async def test_the_dashboard_and_its_files_are_served(tmp_path: Path) -> None:
    dist = build_dist(tmp_path)
    async with running_api(tmp_path / "run", frontend_dir=dist) as rig:
        home = await rig.client.get("/")
        assert home.status_code == 200 and "<title>dash</title>" in home.text
        assert home.headers["cache-control"] == "no-cache"
        asset = await rig.client.get("/assets/app-abc123.js")
        assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
        icon = await rig.client.get("/favicon.svg")
        assert icon.status_code == 200 and icon.headers["content-type"].startswith("image/svg")


async def test_pages_that_only_the_browser_knows_get_the_dashboard(tmp_path: Path) -> None:
    dist = build_dist(tmp_path)
    async with running_api(tmp_path / "run", frontend_dir=dist) as rig:
        for path in ("/groups", "/history", "/signals", "/groups/3/edit"):
            response = await rig.client.get(path)
            assert response.status_code == 200 and "<title>dash</title>" in response.text, path


async def test_the_api_is_never_answered_with_a_page(tmp_path: Path) -> None:
    dist = build_dist(tmp_path)
    async with running_api(tmp_path / "run", frontend_dir=dist) as rig:
        unknown = await rig.client.get("/api/v1/nothing-here")
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "not_found"
        assert (await rig.client.get("/api")).status_code == 404
        assert (await rig.client.get("/api/v1/health")).json()["status"] == "ok"
        assert (await rig.client.get("/docs")).status_code == 200  # FastAPI's own pages still work
        assert (await rig.client.get("/openapi.json")).status_code == 200


async def test_a_missing_file_is_a_404_not_a_page(tmp_path: Path) -> None:
    dist = build_dist(tmp_path)
    async with running_api(tmp_path / "run", frontend_dir=dist) as rig:
        assert (await rig.client.get("/assets/missing.js")).status_code == 404
        assert (await rig.client.get("/nothing.png")).status_code == 404


async def test_files_outside_the_dashboard_folder_are_never_served(tmp_path: Path) -> None:
    dist = build_dist(tmp_path)
    async with running_api(tmp_path / "run", frontend_dir=dist) as rig:
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
            response = await rig.client.get(path)
            assert "do not serve" not in response.text, path


async def test_without_a_build_the_backend_still_runs_and_says_so(tmp_path: Path) -> None:
    async with running_api(tmp_path, frontend_dir=tmp_path / "no-such-folder") as rig:
        assert (await rig.client.get("/")).status_code == 404
        assert (await rig.client.get("/api/v1/health")).status_code == 200


async def test_the_host_and_origin_rules_cover_the_dashboard_too(tmp_path: Path) -> None:
    dist = build_dist(tmp_path)
    settings = settings_for(tmp_path / "x", frontend_dir=dist)
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        refused = await client.get("/", headers={"Host": "evil.example"})
        assert refused.status_code == 403
