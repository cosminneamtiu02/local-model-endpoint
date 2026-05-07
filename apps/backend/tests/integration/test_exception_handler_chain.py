"""Integration tests — RFC 7807 error responses through the real ASGI stack.

These run an in-memory FastAPI app via httpx ASGITransport; no network, no
DB. They exercise the production exception-handler chain end-to-end so the
RFC 7807 wire shape is verified against the same code path consumers will
hit.
"""

# NOTE: ``from __future__ import annotations`` is intentionally OMITTED
# here. The ``_build_app()`` helper below declares route handlers whose
# parameter types are LOCALLY-SCOPED Pydantic models (``_Item``, ``_Bulk``).
# FastAPI's runtime parameter introspection uses ``get_type_hints()`` which
# walks the function's module globals; under deferred annotations the local
# Pydantic class names are unresolvable and FastAPI falls back to treating
# the body params as missing query params (yielding 422 on every request).
# Round-24 lane-1 sweep verified this is the only test file with the pattern.
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from pydantic import BaseModel, Field

from app.api.exception_handler_registry import register_exception_handlers
from app.api.request_id_middleware import RequestIdMiddleware
from app.exceptions import (
    AdapterConnectionFailureError,
    InferenceTimeoutError,
    ModelCapabilityNotSupportedError,
    QueueFullError,
    RegistryNotFoundError,
)
from app.schemas.problem_extras import VALIDATION_ERRORS_MAX_LENGTH
from app.schemas.wire_constants import REQUEST_ID_HEADER
from tests._helpers import assert_problem_json_envelope, make_async_client


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
    async def raise_validate(required_param: int) -> dict[str, Any]:  # noqa: ARG001 — FastAPI signature drives validation; body unused
        return {"ok": True}

    @app.get("/raise/multi-validate")
    async def raise_multi_validate(first_param: int, second_param: int) -> dict[str, Any]:
        return {"ok": first_param + second_param}

    class _Item(BaseModel):
        n: int = Field(ge=0)

    class _Bulk(BaseModel):
        items: list[_Item]

    @app.post("/raise/bulk-validate")
    async def raise_bulk_validate(body: _Bulk) -> dict[str, Any]:
        return {"ok": len(body.items)}

    app.add_middleware(RequestIdMiddleware)
    return app


@pytest.fixture
async def asgi_client() -> AsyncGenerator[AsyncClient]:
    # Constructed via the shared ``make_async_client`` helper so the
    # ``raise_app_exceptions=False`` rationale (lifespan-skip note,
    # transport configuration) lives in exactly one place. ``_build_app``
    # is per-test-file scaffolding; the AsyncClient construction is not.
    async with make_async_client(_build_app()) as c:
        yield c


def _assert_problem_json(response: Response, *, status: int, code: str) -> dict[str, Any]:
    """Thin alias over :func:`tests._helpers.assert_problem_json_envelope`.

    Sets ``check_request_id_correlation=True`` so every integration-tier
    assertion exercises the middleware↔handler correlation contract by
    default. Returns the parsed body for code-specific follow-ups.
    """
    return assert_problem_json_envelope(
        response,
        status=status,
        code=code,
        check_request_id_correlation=True,
    )


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
        "request_id": response.headers[REQUEST_ID_HEADER],
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


async def test_validation_errors_above_cap_returns_422_not_500(
    asgi_client: AsyncClient,
) -> None:
    """A request producing >VALIDATION_ERRORS_MAX_LENGTH errors stays 422, not 500.

    Without the handler-side slice, Pydantic's ``ProblemExtras(max_length=64)``
    would raise on construction, the ValidationError would escape the
    422-handler, and the catch-all 500 handler would ship INTERNAL_ERROR —
    silently demoting a legitimate 422 (non-retryable) into a 500
    (retryable per RFC 9110). This test pins the wire-status invariant.
    """
    too_many = VALIDATION_ERRORS_MAX_LENGTH + 16  # ~80 distinct errors
    body_payload = {"items": [{"n": -1} for _ in range(too_many)]}
    response = await asgi_client.post("/raise/bulk-validate", json=body_payload)
    body = _assert_problem_json(response, status=422, code="VALIDATION_FAILED")
    assert len(body["validation_errors"]) == VALIDATION_ERRORS_MAX_LENGTH
    # Detail surfaces the truncation explicitly.
    assert "first" in body["detail"]
    assert str(VALIDATION_ERRORS_MAX_LENGTH) in body["detail"]
    assert str(too_many) in body["detail"]


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
