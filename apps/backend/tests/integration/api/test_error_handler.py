"""Integration tests for exception handler wire shape."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.exceptions import DomainError
from app.main import create_app
from app.schemas.error_response import ErrorResponse

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class _CustomTestParams(BaseModel):
    foo: str


class _CustomTestError(DomainError):
    """Test-only DomainError subclass for triggering handlers."""

    code = "CUSTOM_TEST"
    http_status = 418

    def __init__(self, foo: str) -> None:
        super().__init__(params=_CustomTestParams(foo=foo))


@pytest.fixture
async def client_with_test_routes() -> AsyncGenerator[AsyncClient]:
    """Build a real app via create_app, attach trigger routes for each handler path."""
    app = create_app()

    @app.get("/_trigger_domain")
    async def trigger_domain() -> None:
        raise _CustomTestError(foo="bar")

    @app.get("/_trigger_validation")
    async def trigger_validation(field_required: str) -> None:  # noqa: ARG001
        # FastAPI returns 422 if 'field_required' is missing in query string;
        # the handler shape gets exercised there.
        return

    @app.get("/_trigger_unhandled")
    async def trigger_unhandled() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    # raise_app_exceptions=False lets the FastAPI exception_handler(Exception)
    # handler convert RuntimeError into the 500/INTERNAL_ERROR envelope so
    # the response body is observable. Default (True) reraises through ASGI.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as c,
    ):
        yield c


async def test_domain_error_handler_emits_canonical_envelope(
    client_with_test_routes: AsyncClient,
) -> None:
    """A raised DomainError subclass serializes to the canonical envelope."""
    response = await client_with_test_routes.get("/_trigger_domain")
    assert response.status_code == 418
    body = response.json()
    parsed = ErrorResponse.model_validate(body)
    assert parsed.error.code == "CUSTOM_TEST"
    assert parsed.error.params == {"foo": "bar"}
    assert parsed.error.details is None
    assert isinstance(parsed.error.request_id, str)
    assert len(parsed.error.request_id) > 0


async def test_validation_error_handler_lists_all_details(
    client_with_test_routes: AsyncClient,
) -> None:
    """RequestValidationError responses include a non-empty details array."""
    response = await client_with_test_routes.get("/_trigger_validation")
    assert response.status_code == 422
    body = response.json()
    parsed = ErrorResponse.model_validate(body)
    assert parsed.error.code == "VALIDATION_FAILED"
    assert parsed.error.details is not None
    assert len(parsed.error.details) >= 1


async def test_unhandled_exception_does_not_leak_message_or_stack(
    client_with_test_routes: AsyncClient,
) -> None:
    """PII discipline: response body must not echo exception class or args."""
    response = await client_with_test_routes.get("/_trigger_unhandled")
    assert response.status_code == 500
    text = response.text
    body = response.json()
    parsed = ErrorResponse.model_validate(body)
    assert parsed.error.code == "INTERNAL_ERROR"
    assert parsed.error.params == {}
    # Locks down the response key-set.
    assert set(body["error"].keys()) <= {"code", "params", "details", "request_id"}
    # PII / debug-info leak guards.
    assert "RuntimeError" not in text, "Exception class name leaked into response"
    assert "boom" not in text, "Exception message leaked into response"


async def test_request_id_is_uuid_format(client_with_test_routes: AsyncClient) -> None:
    """Middleware-issued request_id should be a valid UUID."""
    response = await client_with_test_routes.get("/_trigger_domain")
    assert response.status_code == 418
    body = response.json()
    request_id = body["error"]["request_id"]
    assert _UUID_RE.match(request_id), f"request_id {request_id!r} is not a UUID"
