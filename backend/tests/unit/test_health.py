import httpx

from app.core.config import Settings
from app.main import create_app


async def test_health_ok() -> None:
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "development"
    assert body["background_tasks"] == 0


async def test_health_without_a_running_engine_says_database_unavailable() -> None:
    """Without the lifespan (no startup) there is no database connection and no writer."""
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        body = (await client.get("/api/v1/health")).json()
    assert body["database"] == "unavailable"
    assert body["writer"] is None
    assert body["events_published"] == 0
