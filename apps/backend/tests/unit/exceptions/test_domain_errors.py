"""Tests for generated domain error classes."""

import pytest

from app.exceptions import (
    AdapterConnectionFailureError,
    InferenceTimeoutError,
    InternalError,
    ModelCapabilityNotSupportedError,
    QueueFullError,
    RateLimitedError,
    RegistryNotFoundError,
)


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


def test_queue_full_error() -> None:
    err = QueueFullError(max_waiters=4, current_waiters=5)
    assert err.code == "QUEUE_FULL"
    assert err.http_status == 503
    assert err.type_uri == "urn:lip:error:queue-full"
    assert err.title == "Inference Queue Full"
    assert err.detail() == "Inference queue at capacity (5 waiters, max 4)."
    assert err.params is not None
    assert err.params.model_dump() == {"max_waiters": 4, "current_waiters": 5}


def test_inference_timeout_error() -> None:
    err = InferenceTimeoutError(timeout_seconds=180)
    assert err.code == "INFERENCE_TIMEOUT"
    assert err.http_status == 504
    assert err.type_uri == "urn:lip:error:inference-timeout"
    assert err.detail() == "Inference exceeded the 180-second timeout."


def test_adapter_connection_failure_error() -> None:
    err = AdapterConnectionFailureError(backend="ollama", reason="connection refused")
    assert err.code == "ADAPTER_CONNECTION_FAILURE"
    assert err.http_status == 502
    assert err.type_uri == "urn:lip:error:adapter-connection-failure"
    assert "ollama" in err.detail()
    assert "connection refused" in err.detail()


def test_registry_not_found_error() -> None:
    err = RegistryNotFoundError(model="phantom")
    assert err.code == "REGISTRY_NOT_FOUND"
    assert err.http_status == 404
    assert err.type_uri == "urn:lip:error:registry-not-found"
    assert "phantom" in err.detail()


def test_model_capability_not_supported_error() -> None:
    err = ModelCapabilityNotSupportedError(model="text-only", requested_capability="audio")
    assert err.code == "MODEL_CAPABILITY_NOT_SUPPORTED"
    assert err.http_status == 422
    assert err.type_uri == "urn:lip:error:model-capability-not-supported"
    assert "text-only" in err.detail()
    assert "audio" in err.detail()


def test_internal_error_detail_falls_back_to_title() -> None:
    """Parameterless errors return their title from detail()."""
    err = InternalError()
    assert err.code == "INTERNAL_ERROR"
    assert err.http_status == 500
    assert err.type_uri == "urn:lip:error:internal-error"
    assert err.detail() == err.title
    assert err.title == "Internal Server Error"
    assert err.params is None


def test_queue_full_rejects_missing_required_param() -> None:
    """Required params are positional-keyword on __init__; missing them is a TypeError."""
    with pytest.raises(TypeError):
        QueueFullError(max_waiters=4)  # pyright: ignore[reportCallIssue]
