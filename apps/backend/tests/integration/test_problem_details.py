"""Integration tests — RFC 7807 error responses through the real ASGI stack.

These run an in-memory FastAPI app via httpx ASGITransport; no network, no
DB. They exercise the production exception-handler chain end-to-end so the
RFC 7807 wire shape is verified against the same code path consumers will
hit.
"""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.api.exception_handlers import register_exception_handlers
from app.api.request_id_middleware import RequestIdMiddleware
from app.exceptions import (
    AdapterConnectionFailureError,
    InferenceTimeoutError,
    ModelCapabilityNotSupportedError,
    QueueFullError,
    RegistryNotFoundError,
)
from tests._helpers import assert_problem_json_envelope


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise/queue-full")
    async def raise_queue_full() -> dict[str, Any]:
        raise QueueFullError(max_waiters=4, current_waiters=5)

    @app.get("/raise/timeout")
    async def raise_timeout() -> dict[str, Any]:
        raise InferenceTimeoutError(timeout_seconds=180)

    @app.get("/raise/adapter")
    async def raise_adapter() -> dict[str, Any]:
        raise AdapterConnectionFailureError(backend="ollama", reason="connection refused")

    @app.get("/raise/registry")
    async def raise_registry() -> dict[str, Any]:
        raise RegistryNotFoundError(model_name="phantom-model")

    @app.get("/raise/capability")
    async def raise_capability() -> dict[str, Any]:
        raise ModelCapabilityNotSupportedError(
            model_name="text-only",
            requested_capability="audio",
        )

    @app.get("/raise/unhandled")
    async def raise_unhandled() -> dict[str, Any]:
        msg = "boom — should not appear in response"
        raise RuntimeError(msg)

    @app.get("/raise/validate")
    async def raise_validate(required_param: int) -> dict[str, Any]:  # noqa: ARG001
        return {"ok": True}

    @app.get("/raise/multi-validate")
    async def raise_multi_validate(first_param: int, second_param: int) -> dict[str, Any]:
        return {"ok": first_param + second_param}

    app.add_middleware(RequestIdMiddleware)
    return app


@pytest.fixture
async def asgi_client() -> AsyncGenerator[AsyncClient]:
    # raise_app_exceptions=False mirrors the production code path: under uvicorn,
    # the user-level Exception handler returns the 500 response and the framework
    # re-raises only for telemetry — the consumer always sees the handler's
    # response. Without this flag, ASGITransport re-raises into the test, which
    # is a test-only artifact, not a real-traffic behavior.
    transport = ASGITransport(app=_build_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _assert_problem_json(response: Response, *, status: int, code: str) -> dict[str, Any]:
    """Thin wrapper over :func:`tests._helpers.assert_problem_json_envelope`.

    Adds a fifth integration-tier invariant beyond the shared helper:
      5. Body's ``status`` field equals the wire ``response.status_code``
         (RFC 7807 §3.1 MUST). The handler is the source of truth for both,
         so a divergence here pins a real handler bug.

    Returns the parsed body so the call site can make code-specific assertions.
    """
    body = assert_problem_json_envelope(
        response,
        status=status,
        code=code,
        check_request_id_correlation=True,
    )
    assert body["status"] == status
    return body


# ── DomainError → typed RFC 7807 response ─────────────────────────────────


async def test_queue_full_full_envelope(asgi_client: AsyncClient) -> None:
    response = await asgi_client.get("/raise/queue-full")
    body = _assert_problem_json(response, status=503, code="QUEUE_FULL")
    assert body == {
        "type": "urn:lip:error:queue-full",
        "title": "Inference Queue Full",
        "status": 503,
        "detail": "Inference queue at capacity (5 waiters, max 4).",
        "instance": "/raise/queue-full",
        "code": "QUEUE_FULL",
        "request_id": response.headers["X-Request-ID"],
        "max_waiters": 4,
        "current_waiters": 5,
    }


async def test_inference_timeout_full_envelope(asgi_client: AsyncClient) -> None:
    response = await asgi_client.get("/raise/timeout")
    body = _assert_problem_json(response, status=504, code="INFERENCE_TIMEOUT")
    assert body["timeout_seconds"] == 180
    assert body["instance"] == "/raise/timeout"


async def test_adapter_failure_full_envelope(asgi_client: AsyncClient) -> None:
    response = await asgi_client.get("/raise/adapter")
    body = _assert_problem_json(response, status=502, code="ADAPTER_CONNECTION_FAILURE")
    assert body["backend"] == "ollama"
    assert body["reason"] == "connection refused"


async def test_registry_not_found_full_envelope(asgi_client: AsyncClient) -> None:
    response = await asgi_client.get("/raise/registry")
    body = _assert_problem_json(response, status=404, code="REGISTRY_NOT_FOUND")
    assert body["model_name"] == "phantom-model"


async def test_capability_not_supported_full_envelope(asgi_client: AsyncClient) -> None:
    response = await asgi_client.get("/raise/capability")
    body = _assert_problem_json(response, status=422, code="MODEL_CAPABILITY_NOT_SUPPORTED")
    assert body["model_name"] == "text-only"
    assert body["requested_capability"] == "audio"


# ── RequestValidationError → 422 with validation_errors[] ─────────────────


async def test_pydantic_validation_error_includes_validation_errors_array(
    asgi_client: AsyncClient,
) -> None:
    response = await asgi_client.get("/raise/validate?required_param=not_an_int")
    body = _assert_problem_json(response, status=422, code="VALIDATION_FAILED")
    assert body["type"] == "urn:lip:error:validation-failed"
    assert len(body["validation_errors"]) >= 1
    first = body["validation_errors"][0]
    assert "field" in first
    assert "reason" in first
    assert "required_param" in first["field"]


async def test_multi_field_validation_error_detail_points_to_array(
    asgi_client: AsyncClient,
) -> None:
    """When 2+ fields fail, ``detail`` names the count and refers to validation_errors[]."""
    response = await asgi_client.get("/raise/multi-validate")
    body = _assert_problem_json(response, status=422, code="VALIDATION_FAILED")
    n = len(body["validation_errors"])
    assert n >= 2
    assert body["detail"] == (
        f"Validation failed for {n} fields. See validation_errors[] for details."
    )


# ── Unhandled exception → 500 with no PII / stack leak ────────────────────


async def test_unhandled_exception_returns_500_problem_json(asgi_client: AsyncClient) -> None:
    response = await asgi_client.get("/raise/unhandled")
    body = _assert_problem_json(response, status=500, code="INTERNAL_ERROR")
    assert body["type"] == "urn:lip:error:internal-error"
    # The original exception message must not leak through
    assert "boom" not in body["detail"]
    assert "RuntimeError" not in body["detail"]


# ── HTTPException path (404 from unmatched route) ─────────────────────────


async def test_unmatched_route_returns_404_problem_json(asgi_client: AsyncClient) -> None:
    """An undefined path surfaces as RFC 7807 problem+json via the HTTPException handler."""
    response = await asgi_client.get("/this-route-does-not-exist")
    body = _assert_problem_json(response, status=404, code="NOT_FOUND")
    # 404 routes through NotFoundError so the body matches a typed-raise 404
    # exactly — single source of truth for the wire shape.
    assert body["type"] == "urn:lip:error:not-found"
    assert body["instance"] == "/this-route-does-not-exist"
