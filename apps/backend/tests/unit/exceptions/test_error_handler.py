"""Tests for the RFC 7807 exception handler chain."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import PROBLEM_JSON_MEDIA_TYPE, register_exception_handlers
from app.api.middleware import RequestIdMiddleware
from app.exceptions import (
    AdapterConnectionFailureError,
    InferenceTimeoutError,
    ModelCapabilityNotSupportedError,
    QueueFullError,
    RateLimitedError,
    RegistryNotFoundError,
)


def _create_test_app() -> FastAPI:
    """A minimal app exposing routes that raise each error variant."""
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/trigger-rate-limited")
    async def trigger_rate_limited() -> dict[str, str]:
        raise RateLimitedError(retry_after_seconds=30)

    @test_app.get("/trigger-queue-full")
    async def trigger_queue_full() -> dict[str, str]:
        raise QueueFullError(max_waiters=4, current_waiters=5)

    @test_app.get("/trigger-inference-timeout")
    async def trigger_inference_timeout() -> dict[str, str]:
        raise InferenceTimeoutError(timeout_seconds=180)

    @test_app.get("/trigger-adapter-failure")
    async def trigger_adapter_failure() -> dict[str, str]:
        raise AdapterConnectionFailureError(backend="ollama", reason="connection refused")

    @test_app.get("/trigger-registry-not-found")
    async def trigger_registry_not_found() -> dict[str, str]:
        raise RegistryNotFoundError(model="phantom-model")

    @test_app.get("/trigger-capability-missing")
    async def trigger_capability_missing() -> dict[str, str]:
        raise ModelCapabilityNotSupportedError(model="text-only", requested_capability="audio")

    @test_app.get("/trigger-validation")
    async def trigger_validation(required_param: int) -> dict[str, int]:  # noqa: ARG001
        return {"ok": 1}

    @test_app.get("/trigger-unhandled")
    async def trigger_unhandled() -> dict[str, str]:
        msg = "Something unexpected"
        raise RuntimeError(msg)

    test_app.add_middleware(RequestIdMiddleware)
    return test_app


@pytest.fixture
def test_client() -> TestClient:
    """Provide a TestClient that propagates handled responses (no re-raise)."""
    return TestClient(_create_test_app(), raise_server_exceptions=False)


# ── Domain error path ─────────────────────────────────────────────────────


def test_domain_error_returns_problem_json_content_type(test_client: TestClient) -> None:
    """Every error response sets Content-Type: application/problem+json."""
    response = test_client.get("/trigger-rate-limited")
    assert response.status_code == 429
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)


def test_domain_error_body_has_all_rfc7807_standard_fields(test_client: TestClient) -> None:
    """The body has type, title, status, detail, instance — all required."""
    response = test_client.get("/trigger-queue-full")
    assert response.status_code == 503
    body = response.json()
    assert body["type"] == "urn:lip:error:queue-full"
    assert body["title"] == "Inference Queue Full"
    assert body["status"] == 503
    assert "5 waiters" in body["detail"]
    assert "max 4" in body["detail"]
    assert body["instance"] == "/trigger-queue-full"


def test_domain_error_body_has_lip_extensions(test_client: TestClient) -> None:
    """The body has code (SCREAMING_SNAKE) and request_id (echoes X-Request-ID)."""
    response = test_client.get("/trigger-queue-full")
    body = response.json()
    assert body["code"] == "QUEUE_FULL"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_domain_error_spreads_typed_params_at_root(test_client: TestClient) -> None:
    """Per-error typed params are spread at root level, not nested under 'params'."""
    response = test_client.get("/trigger-queue-full")
    body = response.json()
    assert body["max_waiters"] == 4
    assert body["current_waiters"] == 5
    # Old envelope must be gone
    assert "error" not in body
    assert "params" not in body


def test_domain_error_uses_request_path_for_instance(test_client: TestClient) -> None:
    """instance is the request path, not the full URL or method-prefixed."""
    response = test_client.get("/trigger-rate-limited")
    body = response.json()
    assert body["instance"] == "/trigger-rate-limited"
    # Path only — no scheme, host, port, query, or method
    assert "://" not in body["instance"]
    assert "GET" not in body["instance"]


# ── All five LIP-specific codes — one per code ────────────────────────────


def test_queue_full_maps_to_503(test_client: TestClient) -> None:
    response = test_client.get("/trigger-queue-full")
    assert response.status_code == 503
    assert response.json()["code"] == "QUEUE_FULL"


def test_inference_timeout_maps_to_504(test_client: TestClient) -> None:
    response = test_client.get("/trigger-inference-timeout")
    assert response.status_code == 504
    body = response.json()
    assert body["code"] == "INFERENCE_TIMEOUT"
    assert body["timeout_seconds"] == 180


def test_adapter_connection_failure_maps_to_502(test_client: TestClient) -> None:
    response = test_client.get("/trigger-adapter-failure")
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "ADAPTER_CONNECTION_FAILURE"
    assert body["backend"] == "ollama"
    assert body["reason"] == "connection refused"


def test_registry_not_found_maps_to_404(test_client: TestClient) -> None:
    response = test_client.get("/trigger-registry-not-found")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "REGISTRY_NOT_FOUND"
    assert body["model"] == "phantom-model"


def test_model_capability_not_supported_maps_to_422(test_client: TestClient) -> None:
    response = test_client.get("/trigger-capability-missing")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "MODEL_CAPABILITY_NOT_SUPPORTED"
    assert body["model"] == "text-only"
    assert body["requested_capability"] == "audio"


def test_rate_limited_still_works_under_rfc7807(test_client: TestClient) -> None:
    """Existing generic code RATE_LIMITED keeps mapping correctly post-rewrite."""
    response = test_client.get("/trigger-rate-limited")
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "RATE_LIMITED"
    assert body["retry_after_seconds"] == 30


# ── Validation error path ─────────────────────────────────────────────────


def test_validation_error_maps_to_422_problem_json(test_client: TestClient) -> None:
    """Pydantic RequestValidationError → 422 RFC 7807 with VALIDATION_FAILED."""
    response = test_client.get("/trigger-validation?required_param=not_an_int")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["type"] == "urn:lip:error:validation-failed"
    assert body["title"] == "Validation Failed"
    assert body["status"] == 422


def test_validation_error_body_has_validation_errors_extension(test_client: TestClient) -> None:
    """VALIDATION_FAILED includes a validation_errors[] array of {field, reason}."""
    response = test_client.get("/trigger-validation?required_param=not_an_int")
    body = response.json()
    assert "validation_errors" in body
    assert isinstance(body["validation_errors"], list)
    assert len(body["validation_errors"]) >= 1
    first = body["validation_errors"][0]
    assert "field" in first
    assert "reason" in first


def test_validation_error_field_path_uses_dotted_form(test_client: TestClient) -> None:
    """validation_errors[].field is dotted form of Pydantic's loc tuple."""
    response = test_client.get("/trigger-validation?required_param=not_an_int")
    body = response.json()
    field_path = body["validation_errors"][0]["field"]
    # Query params loc is ("query", "required_param")
    assert "query" in field_path
    assert "required_param" in field_path
    assert "." in field_path


# ── Unhandled exception path ──────────────────────────────────────────────


def test_unhandled_exception_returns_500_problem_json(test_client: TestClient) -> None:
    response = test_client.get("/trigger-unhandled")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["type"] == "urn:lip:error:internal-error"
    assert body["status"] == 500


def test_unhandled_exception_does_not_leak_pii_or_stack(test_client: TestClient) -> None:
    """The 500 detail is the static title — never the underlying exception text."""
    response = test_client.get("/trigger-unhandled")
    body = response.json()
    assert "Something unexpected" not in body["detail"]
    assert "RuntimeError" not in body["detail"]
    assert "Traceback" not in body["detail"]
    # No nested 'params' key (INTERNAL_ERROR is parameterless)
    assert "params" not in body


def test_unhandled_exception_still_includes_request_id(test_client: TestClient) -> None:
    """The body carries request_id for log correlation even on the 500 path.

    Note: the X-Request-ID *response header* is intentionally not asserted
    here. Starlette's ``BaseHTTPMiddleware`` does not run its post-call_next
    code when the inner app raises an exception type that is not registered
    via ``app.exception_handler`` — the catch-all 500 response is produced by
    ``ServerErrorMiddleware`` further out. The handler-side ``request_id`` in
    the body is still populated because the middleware sets
    ``request.state.request_id`` *before* ``call_next``. Hardening that gap
    (writing the header even on unhandled exceptions) is a middleware
    concern, not an F004 concern.
    """
    response = test_client.get("/trigger-unhandled")
    body = response.json()
    assert isinstance(body["request_id"], str)
    assert len(body["request_id"]) > 0


# ── Handler ordering ──────────────────────────────────────────────────────


def test_domain_error_handler_takes_priority_over_generic(test_client: TestClient) -> None:
    """A DomainError must hit the typed handler, not the generic Exception fallback."""
    response = test_client.get("/trigger-queue-full")
    body = response.json()
    # If the generic handler had run, we'd see INTERNAL_ERROR (500) and no params.
    assert body["code"] == "QUEUE_FULL"
    assert response.status_code == 503
    assert body["max_waiters"] == 4
