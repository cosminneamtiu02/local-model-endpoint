"""Integration tests for RequestIdMiddleware (mounted on the FastAPI app).

Uses /health as a benign sink to drive the middleware behavior; the
endpoint itself is covered by ``test_health.py``. Splitting this out of
test_health.py mirrors the production module name so a reviewer hunting
for X-Request-ID coverage greps the obvious filename.
"""

from httpx import AsyncClient

from app.api.request_id_middleware import _MAX_REQUEST_BODY_BYTES
from app.schemas.wire_constants import REQUEST_ID_HEADER, UUID_REGEX


async def test_response_includes_x_request_id(client: AsyncClient) -> None:
    """Every response should include a UUID-shaped X-Request-ID header."""
    response = await client.get("/health")
    assert REQUEST_ID_HEADER in response.headers
    # Pin the UUID shape (not just non-empty) — a regression that emits
    # ``"x"`` or any short non-UUID string would otherwise pass.
    assert UUID_REGEX.match(response.headers[REQUEST_ID_HEADER]) is not None


async def test_request_id_uses_client_provided_uuid(client: AsyncClient) -> None:
    """A valid client-provided UUID should be echoed back in the response."""
    client_uuid = "12345678-1234-1234-1234-123456789012"
    response = await client.get("/health", headers={REQUEST_ID_HEADER: client_uuid})
    assert response.headers[REQUEST_ID_HEADER] == client_uuid


async def test_request_id_rejects_invalid_client_id(client: AsyncClient) -> None:
    """A non-UUID client-provided ID should be replaced with a fresh UUID-shaped one."""
    response = await client.get("/health", headers={REQUEST_ID_HEADER: "not-a-uuid"})
    assert response.headers[REQUEST_ID_HEADER] != "not-a-uuid"
    # Replacement must be UUID-shaped (regression guard against the
    # middleware emitting any non-empty string under the rejection branch).
    assert UUID_REGEX.match(response.headers[REQUEST_ID_HEADER]) is not None


async def test_oversize_content_length_rejected_with_413_problem_json(client: AsyncClient) -> None:
    """Content-Length above the body-size cap is rejected before the body buffers.

    The middleware sends an RFC 7807 problem+json envelope without invoking
    the typed exception-handler chain (which sits below it in the stack).
    The bound is read from the module constant rather than re-derived as a
    literal so a future cap bump doesn't silently desync the test from the
    source-of-truth boundary.
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
    assert response.headers[REQUEST_ID_HEADER] == body["request_id"]
