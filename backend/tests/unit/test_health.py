import httpx

from app.core.config import Settings
from app.main import create_app


async def test_health_ok() -> None:
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "development"
    assert body["background_tasks"] == 0
