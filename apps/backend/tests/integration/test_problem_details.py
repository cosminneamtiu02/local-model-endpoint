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
from httpx import ASGITransport, AsyncClient

from app.api.errors import PROBLEM_JSON_MEDIA_TYPE, register_exception_handlers
from app.api.middleware import RequestIdMiddleware
from app.exceptions import (
    AdapterConnectionFailureError,
    InferenceTimeoutError,
    ModelCapabilityNotSupportedError,
    QueueFullError,
    RegistryNotFoundError,
)


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
        raise RegistryNotFoundError(model="phantom-model")

    @app.get("/raise/capability")
    async def raise_capability() -> dict[str, Any]:
        raise ModelCapabilityNotSupportedError(
            model="text-only",
            requested_capability="audio",
        )

    @app.get("/raise/unhandled")
    async def raise_unhandled() -> dict[str, Any]:
        msg = "boom — should not appear in response"
        raise RuntimeError(msg)

    @app.get("/raise/validate")
    async def raise_validate(required_param: int) -> dict[str, Any]:  # noqa: ARG001
        return {"ok": True}

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


# ── DomainError → typed RFC 7807 response ─────────────────────────────────


async def test_queue_full_full_envelope(asgi_client: AsyncClient) -> None:
    response = await asgi_client.get("/raise/queue-full")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body = response.json()
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
    assert response.status_code == 504
    body = response.json()
    assert body["code"] == "INFERENCE_TIMEOUT"
    assert body["timeout_seconds"] == 180
    assert body["instance"] == "/raise/timeout"


async def test_adapter_failure_full_envelope(asgi_client: AsyncClient) -> None:
    response = await asgi_client.get("/raise/adapter")
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "ADAPTER_CONNECTION_FAILURE"
    assert body["backend"] == "ollama"
    assert body["reason"] == "connection refused"


async def test_registry_not_found_full_envelope(asgi_client: AsyncClient) -> None:
    response = await asgi_client.get("/raise/registry")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "REGISTRY_NOT_FOUND"
    assert body["model"] == "phantom-model"


async def test_capability_not_supported_full_envelope(asgi_client: AsyncClient) -> None:
    response = await asgi_client.get("/raise/capability")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "MODEL_CAPABILITY_NOT_SUPPORTED"
    assert body["model"] == "text-only"
    assert body["requested_capability"] == "audio"


# ── RequestValidationError → 422 with validation_errors[] ─────────────────


async def test_pydantic_validation_error_includes_validation_errors_array(
    asgi_client: AsyncClient,
) -> None:
    response = await asgi_client.get("/raise/validate?required_param=not_an_int")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["type"] == "urn:lip:error:validation-failed"
    assert len(body["validation_errors"]) >= 1
    first = body["validation_errors"][0]
    assert "field" in first
    assert "reason" in first
    assert "required_param" in first["field"]


# ── Unhandled exception → 500 with no PII / stack leak ────────────────────


async def test_unhandled_exception_returns_500_problem_json(asgi_client: AsyncClient) -> None:
    response = await asgi_client.get("/raise/unhandled")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["type"] == "urn:lip:error:internal-error"
    # The original exception message must not leak through
    assert "boom" not in body["detail"]
    assert "RuntimeError" not in body["detail"]
