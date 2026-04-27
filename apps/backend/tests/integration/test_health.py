"""Integration tests for /health and request-ID middleware."""

from httpx import AsyncClient


async def test_health_returns_200(client: AsyncClient) -> None:
    """GET /health should return 200 with status ok."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_response_includes_x_request_id(client: AsyncClient) -> None:
    """Every response should include an X-Request-ID header."""
    response = await client.get("/health")
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


async def test_request_id_uses_client_provided_uuid(client: AsyncClient) -> None:
    """A valid client-provided UUID should be echoed back in the response."""
    client_uuid = "12345678-1234-1234-1234-123456789012"
    response = await client.get("/health", headers={"X-Request-ID": client_uuid})
    assert response.headers["X-Request-ID"] == client_uuid


async def test_request_id_rejects_invalid_client_id(client: AsyncClient) -> None:
    """A non-UUID client-provided ID should be replaced with a fresh server-generated one."""
    response = await client.get("/health", headers={"X-Request-ID": "not-a-uuid"})
    assert response.headers["X-Request-ID"] != "not-a-uuid"
    assert len(response.headers["X-Request-ID"]) > 0
