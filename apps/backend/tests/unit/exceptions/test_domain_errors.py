"""Tests for generated domain error classes."""

from typing import ClassVar

import pytest

from app.exceptions import (
    AdapterConnectionFailureError,
    ConflictError,
    InferenceTimeoutError,
    InternalError,
    ModelCapabilityNotSupportedError,
    NotFoundError,
    QueueFullError,
    RateLimitedError,
    RegistryNotFoundError,
)
from app.exceptions.base import DomainError


def test_rate_limited_constructs_with_typed_params() -> None:
    """RateLimitedError construct + classvar shape (smoke test for the existing generic code)."""
    error = RateLimitedError(retry_after_seconds=60)

    assert error.code == "RATE_LIMITED"
    assert error.http_status == 429
    assert error.type_uri == "urn:lip:error:rate-limited"
    assert error.title == "Too Many Requests"
    assert error.params is not None
    assert error.params.model_dump() == {"retry_after_seconds": 60}
    assert "RATE_LIMITED" in str(error)


def test_queue_full_constructs_with_typed_params() -> None:
    err = QueueFullError(max_waiters=4, current_waiters=5)
    assert err.code == "QUEUE_FULL"
    assert err.http_status == 503
    assert err.type_uri == "urn:lip:error:queue-full"
    assert err.title == "Inference Queue Full"
    assert err.detail() == "Inference queue at capacity (5 waiters, max 4)."
    assert err.params is not None
    assert err.params.model_dump() == {"max_waiters": 4, "current_waiters": 5}


def test_inference_timeout_carries_504_and_typed_params() -> None:
    err = InferenceTimeoutError(timeout_seconds=180)
    assert err.code == "INFERENCE_TIMEOUT"
    assert err.http_status == 504
    assert err.type_uri == "urn:lip:error:inference-timeout"
    assert err.detail() == "Inference exceeded the 180-second timeout."


def test_adapter_connection_failure_renders_backend_and_reason() -> None:
    err = AdapterConnectionFailureError(backend="ollama", reason="connection refused")
    assert err.code == "ADAPTER_CONNECTION_FAILURE"
    assert err.http_status == 502
    assert err.type_uri == "urn:lip:error:adapter-connection-failure"
    assert "ollama" in err.detail()
    assert "connection refused" in err.detail()


def test_registry_not_found_renders_model_in_detail() -> None:
    err = RegistryNotFoundError(model_name="phantom")
    assert err.code == "REGISTRY_NOT_FOUND"
    assert err.http_status == 404
    assert err.type_uri == "urn:lip:error:registry-not-found"
    assert "phantom" in err.detail()


def test_model_capability_not_supported_renders_model_and_capability() -> None:
    err = ModelCapabilityNotSupportedError(model_name="text-only", requested_capability="audio")
    assert err.code == "MODEL_CAPABILITY_NOT_SUPPORTED"
    assert err.http_status == 422
    assert err.type_uri == "urn:lip:error:model-capability-not-supported"
    assert "text-only" in err.detail()
    assert "audio" in err.detail()


def test_conflict_constructs_with_default_detail() -> None:
    """ConflictError closes the unit-coverage gap flagged in earlier reviews.

    The registry-shape test in test_registry.py only iterates the keys; without
    a per-class assertion of code/status/type_uri/title/detail, a YAML edit
    breaking ``CONFLICT`` would have shipped green.
    """
    err = ConflictError()
    assert err.code == "CONFLICT"
    assert err.http_status == 409
    assert err.type_uri == "urn:lip:error:conflict"
    assert err.title == "Conflict"
    assert err.detail() == "The operation conflicts with the current resource state."


def test_internal_error_detail_returns_detail_template() -> None:
    """Parameterless errors return their detail_template (or fall back to title) from detail()."""
    err = InternalError()
    assert err.code == "INTERNAL_ERROR"
    assert err.http_status == 500
    assert err.type_uri == "urn:lip:error:internal-error"
    assert err.title == "Internal Server Error"
    assert err.detail() == (
        "An unexpected error occurred. Use the request_id to correlate with server logs."
    )
    assert err.params is None


def test_not_found_constructs_with_default_detail() -> None:
    """NotFoundError per-class invariants — closes a unit-coverage gap.

    The registry-shape test only iterates the keys; without a focused
    assertion of code/status/type_uri/title/detail, a YAML edit breaking
    NOT_FOUND would only surface via integration tests.
    """
    err = NotFoundError()
    assert err.code == "NOT_FOUND"
    assert err.http_status == 404
    assert err.type_uri == "urn:lip:error:not-found"
    assert err.title == "Resource Not Found"
    assert err.detail() == "The requested resource does not exist."
    assert err.params is None


def test_queue_full_rejects_missing_required_param() -> None:
    """Required params are positional-keyword on __init__; missing them is a TypeError."""
    with pytest.raises(TypeError):
        QueueFullError(max_waiters=4)  # pyright: ignore[reportCallIssue]


def test_domain_error_subclass_missing_classvar_raises_typeerror() -> None:
    """__init_subclass__ enforces that every DomainError declares the 5 required ClassVars."""
    with pytest.raises(TypeError, match="must declare ClassVar"):
        # type_uri is intentionally missing — should fail at class-creation time.
        class _BrokenError(DomainError):  # pyright: ignore[reportUnusedClass]
            code: ClassVar[str] = "BROKEN"
            http_status: ClassVar[int] = 500
            title: ClassVar[str] = "Broken"
            detail_template: ClassVar[str] = "broken"


def test_domain_error_str_does_not_leak_params() -> None:
    """Exception.args carries the code only — never the params (PII safety invariant)."""
    err = QueueFullError(max_waiters=12345, current_waiters=99999)
    rendered = str(err)
    assert "QUEUE_FULL" in rendered
    assert "12345" not in rendered
    assert "99999" not in rendered
    # And Exception.args itself contains exactly the code.
    assert err.args == ("QUEUE_FULL",)


def test_parameterized_error_detail_works_under_python_o() -> None:
    """detail() must succeed even when assertions are stripped (Python -O).

    Generated subclasses use ``cast("BaseModel", self.params)`` instead of
    ``assert self.params is not None`` so the narrowing survives -O. This test
    documents the contract — it doesn't actually re-launch under -O (pytest
    doesn't run with -O by default), but a regression that re-introduced an
    ``assert`` would be caught by static checkers (pyright strict) at CI time.
    """
    err = QueueFullError(max_waiters=4, current_waiters=5)
    rendered = err.detail()
    # The rendered string interpolates both params — proving the cast path
    # produced a real BaseModel that model_dump() could traverse.
    assert "5 waiters" in rendered
    assert "max 4" in rendered
