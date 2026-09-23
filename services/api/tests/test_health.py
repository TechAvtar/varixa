from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["service"] == "Verixa API"
    assert body["environment"] == "test"
    assert "version" in body


async def test_health_does_not_leak_settings(client: AsyncClient) -> None:
    body = (await client.get("/health")).json()
    assert set(body) == {
        "status",
        "service",
        "version",
        "environment",
        "database",
        "storage",
        "providers",
        "uptime_seconds",
    }
