"""Tests for the RFC 7807 exception handler chain."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.exception_handler_registry import register_exception_handlers
from app.api.request_id_middleware import RequestIdMiddleware
from app.exceptions import (
    AdapterConnectionFailureError,
    InferenceTimeoutError,
    ModelCapabilityNotSupportedError,
    QueueFullError,
    RateLimitedError,
    RegistryNotFoundError,
)
from app.schemas import ValidationErrorDetail
from app.schemas.wire_constants import PROBLEM_JSON_MEDIA_TYPE, REQUEST_ID_HEADER


def _create_test_app() -> FastAPI:  # noqa: C901 — flat list of 10 trigger routes is the simplest expression
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
        raise RegistryNotFoundError(model_name="phantom-model")

    @test_app.get("/trigger-capability-missing")
    async def trigger_capability_missing() -> dict[str, str]:
        raise ModelCapabilityNotSupportedError(model_name="text-only", requested_capability="audio")

    @test_app.get("/trigger-validation")
    async def trigger_validation(required_param: int) -> dict[str, int]:  # noqa: ARG001 — FastAPI signature drives validation; body unused
        return {"ok": 1}

    @test_app.get("/trigger-multi-validation")
    async def trigger_multi_validation(first_param: int, second_param: int) -> dict[str, int]:
        return {"ok": first_param + second_param}

    @test_app.get("/trigger-unhandled")
    async def trigger_unhandled() -> dict[str, str]:
        msg = "Something unexpected"
        raise RuntimeError(msg)

    @test_app.get("/trigger-http-405")
    async def trigger_http_405() -> dict[str, str]:
        # ``headers={"Allow": "POST"}`` exercises the ``Allow`` forwarding
        # path through ``_problem_response(extra_headers=...)``. Without
        # explicit headers the typed-405 path silently ships RFC-9110-
        # non-compliant responses.
        raise HTTPException(status_code=405, headers={"Allow": "POST"})

    @test_app.get("/trigger-http-405-without-allow")
    async def trigger_http_405_without_allow() -> dict[str, str]:
        # Negative companion to ``trigger-http-405``: a typed
        # ``HTTPException(405)`` without an ``Allow`` header — exercises
        # the defensive log branch that surfaces this RFC 9110 §15.5.6
        # violation. The wire response still ships with the correct
        # MethodNotAllowedError envelope; the operator-side signal is
        # the ``http_exception_405_missing_allow_header`` log line.
        raise HTTPException(status_code=405)

    @test_app.post("/post-only")
    async def post_only() -> dict[str, str]:
        # Real framework-405 vector: Starlette's ``Route.handle`` raises
        # ``HTTPException(405, headers={"Allow": "POST"})`` automatically
        # for a method mismatch on a registered route. The handler chain
        # must forward Starlette's ``Allow`` header to the response per
        # RFC 9110 §15.5.6.
        return {"ok": "1"}

    test_app.add_middleware(RequestIdMiddleware)
    return test_app


@pytest.fixture
def client() -> TestClient:
    """Provide a TestClient that propagates handled responses (no re-raise)."""
    return TestClient(_create_test_app(), raise_server_exceptions=False)


# ── Domain error path ─────────────────────────────────────────────────────


def test_domain_error_returns_problem_json_content_type(client: TestClient) -> None:
    """Every error response sets Content-Type: application/problem+json; charset=utf-8."""
    response = client.get("/trigger-rate-limited")
    assert response.status_code == 429
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)


def test_domain_error_response_includes_content_language_en(client: TestClient) -> None:
    """Every error response advertises Content-Language: en (RFC 7807 §3.1)."""
    response = client.get("/trigger-rate-limited")
    assert response.headers["content-language"] == "en"


def test_domain_error_body_has_all_rfc7807_standard_fields(client: TestClient) -> None:
    """The body has type, title, status, detail, instance — all required."""
    response = client.get("/trigger-queue-full")
    assert response.status_code == 503
    body = response.json()
    assert body["type"] == "urn:lip:error:queue-full"
    assert body["title"] == "Inference Queue Full"
    assert body["status"] == 503
    assert "5 waiters" in body["detail"]
    assert "max 4" in body["detail"]
    assert body["instance"] == "/trigger-queue-full"


def test_domain_error_body_has_lip_extensions(client: TestClient) -> None:
    """The body has code (SCREAMING_SNAKE) and request_id (echoes X-Request-ID)."""
    response = client.get("/trigger-queue-full")
    body = response.json()
    assert body["code"] == "QUEUE_FULL"
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_domain_error_spreads_typed_params_at_root(client: TestClient) -> None:
    """Per-error typed params are spread at root level, not nested under 'params'."""
    response = client.get("/trigger-queue-full")
    body = response.json()
    assert body["max_waiters"] == 4
    assert body["current_waiters"] == 5
    # Old envelope must be gone
    assert "error" not in body
    assert "params" not in body


def test_domain_error_uses_request_path_for_instance(client: TestClient) -> None:
    """instance is the request path, not the full URL or method-prefixed."""
    response = client.get("/trigger-rate-limited")
    body = response.json()
    assert body["instance"] == "/trigger-rate-limited"
    # Path only — no scheme, host, port, query, or method
    assert "://" not in body["instance"]
    assert "GET" not in body["instance"]


# ── All five LIP-specific codes — one per code ────────────────────────────


def test_queue_full_maps_to_503(client: TestClient) -> None:
    response = client.get("/trigger-queue-full")
    assert response.status_code == 503
    assert response.json()["code"] == "QUEUE_FULL"


def test_inference_timeout_maps_to_504(client: TestClient) -> None:
    response = client.get("/trigger-inference-timeout")
    assert response.status_code == 504
    body = response.json()
    assert body["code"] == "INFERENCE_TIMEOUT"
    assert body["timeout_seconds"] == 180


def test_adapter_connection_failure_maps_to_502(client: TestClient) -> None:
    response = client.get("/trigger-adapter-failure")
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "ADAPTER_CONNECTION_FAILURE"
    assert body["backend"] == "ollama"
    assert body["reason"] == "connection refused"


def test_registry_not_found_maps_to_404(client: TestClient) -> None:
    response = client.get("/trigger-registry-not-found")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "REGISTRY_NOT_FOUND"
    assert body["model_name"] == "phantom-model"


def test_model_capability_not_supported_maps_to_422(client: TestClient) -> None:
    response = client.get("/trigger-capability-missing")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "MODEL_CAPABILITY_NOT_SUPPORTED"
    assert body["model_name"] == "text-only"
    assert body["requested_capability"] == "audio"


def test_rate_limited_still_works_under_rfc7807(client: TestClient) -> None:
    """Existing generic code RATE_LIMITED keeps mapping correctly post-rewrite."""
    response = client.get("/trigger-rate-limited")
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "RATE_LIMITED"
    assert body["retry_after_seconds"] == 30


# ── Validation error path ─────────────────────────────────────────────────


def test_validation_error_maps_to_422_problem_json(client: TestClient) -> None:
    """Pydantic RequestValidationError → 422 RFC 7807 with VALIDATION_FAILED."""
    response = client.get("/trigger-validation?required_param=not_an_int")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["type"] == "urn:lip:error:validation-failed"
    assert body["title"] == "Validation Failed"
    assert body["status"] == 422


def test_validation_error_body_has_validation_errors_extension(client: TestClient) -> None:
    """VALIDATION_FAILED includes a validation_errors[] array of {field, reason}."""
    response = client.get("/trigger-validation?required_param=not_an_int")
    body = response.json()
    assert "validation_errors" in body
    assert isinstance(body["validation_errors"], list)
    assert len(body["validation_errors"]) >= 1
    first = body["validation_errors"][0]
    assert "field" in first
    assert "reason" in first


def test_validation_error_entries_match_validation_error_detail_shape(
    client: TestClient,
) -> None:
    """Each validation_errors[] item is exactly {field, reason} — no extras leak."""
    response = client.get("/trigger-validation?required_param=not_an_int")
    body = response.json()
    first = body["validation_errors"][0]
    # Only the two keys allowed by the ValidationErrorDetail schema (extra='forbid').
    assert set(first.keys()) == {"field", "reason"}
    # And the dict re-validates cleanly through the schema as a sanity check.
    detail = ValidationErrorDetail.model_validate(first)
    assert detail.field == first["field"]
    assert detail.reason == first["reason"]


def test_validation_error_field_path_uses_dotted_form(client: TestClient) -> None:
    """validation_errors[].field is dotted form of Pydantic's loc tuple."""
    response = client.get("/trigger-validation?required_param=not_an_int")
    body = response.json()
    field_path = body["validation_errors"][0]["field"]
    # Query params loc is ("query", "required_param")
    assert "query" in field_path
    assert "required_param" in field_path
    assert "." in field_path


def test_multi_field_validation_error_detail_points_to_array(client: TestClient) -> None:
    """When >1 fields fail, the detail names the count and refers to validation_errors[]."""
    # Both query params are missing AND would coerce to int — two errors.
    response = client.get("/trigger-multi-validation")
    assert response.status_code == 422
    body = response.json()
    assert len(body["validation_errors"]) >= 2
    n = len(body["validation_errors"])
    assert body["detail"] == (
        f"Validation failed for {n} fields. See validation_errors[] for details."
    )


# ── Unhandled exception path ──────────────────────────────────────────────


def test_unhandled_exception_returns_500_problem_json(client: TestClient) -> None:
    response = client.get("/trigger-unhandled")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["type"] == "urn:lip:error:internal-error"
    assert body["status"] == 500


def test_unhandled_exception_does_not_leak_pii_or_stack(client: TestClient) -> None:
    """The 500 detail is the static title — never the underlying exception text."""
    response = client.get("/trigger-unhandled")
    body = response.json()
    assert "Something unexpected" not in body["detail"]
    assert "RuntimeError" not in body["detail"]
    assert "Traceback" not in body["detail"]
    # No nested 'params' key (INTERNAL_ERROR is parameterless)
    assert "params" not in body


def test_unhandled_exception_request_id_matches_response_header(client: TestClient) -> None:
    """The 500 path now sets X-Request-ID on the JSONResponse, so body and header match."""
    response = client.get("/trigger-unhandled")
    body = response.json()
    assert isinstance(body["request_id"], str)
    assert len(body["request_id"]) > 0
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


# ── Handler ordering ──────────────────────────────────────────────────────


def test_domain_error_handler_takes_priority_over_generic(client: TestClient) -> None:
    """A DomainError must hit the typed handler, not the generic Exception fallback."""
    response = client.get("/trigger-queue-full")
    body = response.json()
    # If the generic handler had run, we'd see INTERNAL_ERROR (500) and no params.
    assert body["code"] == "QUEUE_FULL"
    assert response.status_code == 503
    assert body["max_waiters"] == 4


# ── HTTPException path (404 missing route, 405 method mismatch) ───────────


def test_http_exception_405_returns_typed_method_not_allowed_problem_json(
    client: TestClient,
) -> None:
    """Framework-405 routes through ``MethodNotAllowedError`` for wire-shape parity.

    Single source of truth for the 405 envelope: a typed
    ``raise MethodNotAllowedError()`` from a route and a framework
    ``HTTPException(405)`` ship the same ``type`` URN, mirroring the 404
    branch's typed-vs-framework symmetry.
    """
    response = client.get("/trigger-http-405")
    assert response.status_code == 405
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body = response.json()
    assert body["type"] == "urn:lip:error:method-not-allowed"
    assert body["status"] == 405
    assert body["code"] == "METHOD_NOT_ALLOWED"
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_http_exception_405_forwards_allow_header(client: TestClient) -> None:
    """The 405 path forwards ``Allow:`` headers per RFC 9110 §15.5.6.

    A standards-compliant client (curl --retry, requests Retry adapter)
    cannot discover supported methods on a 405 if the header is missing.
    The handler explicitly forwards ``http_exc.headers`` to the response;
    a regression that drops ``extra_headers=`` would silently ship non-
    compliant 405s — this test pins the contract on the wire.
    """
    response = client.get("/trigger-http-405")
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


def test_http_exception_405_without_allow_header_emits_defensive_log(
    client: TestClient,
) -> None:
    """A typed ``HTTPException(405)`` without an Allow header logs a
    conformance-gap warning.

    The framework-auto-405 path always sets the Allow header (per
    Starlette's ``Route.handle``), and the typed-DomainError surface
    is ``MethodNotAllowedError`` (which routes through the
    ``MethodNotAllowedError()`` builder, not ``HTTPException``). A typed
    ``HTTPException(status_code=405)`` from app code without
    ``headers={"Allow": ...}`` would silently violate RFC 9110 §15.5.6.
    The defensive log line surfaces this regression class so an
    operator can trace it back to the offending raise site.
    """
    import structlog.testing

    with structlog.testing.capture_logs() as captured:
        response = client.get("/trigger-http-405-without-allow")

    # The wire response is still a clean MethodNotAllowedError envelope
    # (RFC 7807 typed) — the defensive log is the only operator-side
    # signal, the response itself isn't degraded.
    assert response.status_code == 405
    body = response.json()
    assert body["code"] == "METHOD_NOT_ALLOWED"

    # The defensive log line landed; the wire path still got the typed
    # 405 envelope above.
    missing_allow = [
        e for e in captured if e.get("event") == "http_exception_405_missing_allow_header"
    ]
    assert len(missing_allow) == 1, captured
    assert missing_allow[0]["method"] == "GET"
    assert missing_allow[0]["path"] == "/trigger-http-405-without-allow"


def test_framework_405_on_method_mismatch_includes_allow_header(client: TestClient) -> None:
    """A real method-mismatch 405 (no typed raise) carries Starlette's auto Allow header.

    Mounts a POST-only route and GETs it — Starlette's ``Route.handle``
    auto-raises ``HTTPException(405, headers={"Allow": "POST"})``, and
    the handler chain must round-trip the ``Allow`` header into the
    wire response. This is the canonical framework-405 vector that
    dashboarding clients see; the typed-route ``HTTPException(405,
    headers=...)`` in the test above is the unit-tier mirror.
    """
    response = client.get("/post-only")
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
    body = response.json()
    assert body["code"] == "METHOD_NOT_ALLOWED"


def test_unmatched_route_returns_about_blank_404_problem_json(client: TestClient) -> None:
    """A request for an undefined route surfaces RFC 7807 with code NOT_FOUND."""
    response = client.get("/this-route-does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body = response.json()
    # 404 routes through NotFoundError (typed URN), not about:blank.
    assert body["type"] == "urn:lip:error:not-found"
    assert body["status"] == 404
    assert body["code"] == "NOT_FOUND"
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


# ── Defensive raise on extras collision ────────────────────────────────────


def test_build_problem_payload_raises_internal_error_on_extras_collision() -> None:
    """A typed-params key colliding with a ProblemExtras key raises
    ``InternalError`` (defense-in-depth invariant).

    The codegen's ``RESERVED_PARAM_NAMES`` set prevents this collision
    at YAML-validation time, but the runtime guard exists in case the
    YAML/codegen invariant ever drifts. The raise propagates to
    ``_handle_unhandled_exception`` which renders a clean InternalError
    problem+json regardless of the original exc type. This test
    exercises the runtime guard directly via an artificially-crafted
    Pydantic model whose fields collide with ``ProblemExtras``.
    """
    from typing import ClassVar
    from unittest.mock import MagicMock

    from pydantic import BaseModel, ConfigDict

    from app.api.exception_handler_registry import _build_problem_payload
    from app.exceptions import DomainError, InternalError, QueueFullError
    from app.schemas import ProblemExtras, ValidationErrorDetail

    class _CollidingParams(BaseModel):
        # ``validation_errors`` is the only field on ``ProblemExtras``
        # today; a typed-param of the same name simulates a future
        # YAML/codegen invariant violation. The codegen
        # ``RESERVED_PARAM_NAMES`` guard would catch this at build
        # time; this test exercises the runtime defense.
        model_config = ConfigDict(frozen=True)
        validation_errors: list[dict[str, str]]

    class _CollidingError(DomainError):
        code: ClassVar[str] = "ARTIFICIAL_COLLISION"
        http_status: ClassVar[int] = 500
        type_uri: ClassVar[str] = "urn:lip:error:artificial-collision"
        title: ClassVar[str] = "Artificial Collision"
        detail_template: ClassVar[str] = "collision-detail"

        def __init__(self) -> None:
            super().__init__(
                params=_CollidingParams(validation_errors=[{"field": "x", "reason": "y"}]),
            )

    # Construct an extras with the same key.
    extras = ProblemExtras(
        validation_errors=[ValidationErrorDetail(field="other", reason="value")],
    )

    # Mock request — _bounded_instance reads request.url.path; provide
    # one so the helper doesn't fail at the instance-construction step
    # (which it never reaches because the collision raise fires first).
    mock_request = MagicMock()
    mock_request.url.path = "/test"

    # Use the existing QueueFullError as a sanity precondition: without
    # a collision, _build_problem_payload should succeed. Then the
    # _CollidingError + extras combination must raise InternalError.
    sane = QueueFullError(max_waiters=4, current_waiters=5)
    payload = _build_problem_payload(
        sane,
        mock_request,
        request_id="00000000-0000-4000-8000-000000000abc",
    )
    assert payload.code == "QUEUE_FULL"

    with pytest.raises(InternalError):
        _build_problem_payload(
            _CollidingError(),
            mock_request,
            request_id="00000000-0000-4000-8000-000000000abc",
            extras=extras,
        )
