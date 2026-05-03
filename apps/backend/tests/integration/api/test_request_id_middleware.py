"""Integration tests for RequestIdMiddleware (mounted on the FastAPI app).

Uses /health as a benign sink to drive the middleware behaviour; the
endpoint itself is covered by ``test_health.py``. Splitting this out of
test_health.py mirrors the production module name (lane-4 finding) so a
reviewer hunting for X-Request-ID coverage greps the obvious filename.
"""

from httpx import AsyncClient

from app.api.request_id_middleware import _MAX_REQUEST_BODY_BYTES


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


async def test_oversize_content_length_rejected_with_413_problem_json(client: AsyncClient) -> None:
    """Content-Length above the body-size cap is rejected before the body buffers.

    The middleware sends an RFC 7807 problem+json envelope without invoking
    the typed exception-handler chain (which sits below it in the stack).
    The bound is read from the module constant rather than re-derived as a
    literal so a future cap bump doesn't silently desync the test from the
    source-of-truth boundary (lane-20 finding 20.5).
    """
    oversize = _MAX_REQUEST_BODY_BYTES + 1
    response = await client.post(
        "/health",
        headers={"Content-Length": str(oversize), "Content-Type": "application/json"},
        content=b"",  # body is irrelevant — the Content-Length lie is what trips the guard
    )
    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json; charset=utf-8"
    body = response.json()
    assert body["status"] == 413
    assert body["code"] == "REQUEST_TOO_LARGE"
    assert body["title"] == "Payload Too Large"
    assert body["instance"] == "/health"
    assert "request_id" in body
    assert response.headers["X-Request-ID"] == body["request_id"]
