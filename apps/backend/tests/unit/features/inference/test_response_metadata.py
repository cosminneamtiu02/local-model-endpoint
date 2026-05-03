"""Unit tests for ResponseMetadata (LIP-E001-F001)."""

import pytest
from pydantic import ValidationError

from app.features.inference.schemas.response_metadata import ResponseMetadata

# UUID-shaped request_id, mirroring the wire-contract pattern enforced by
# both the middleware and ProblemDetails.request_id. ResponseMetadata is
# now schema-clamped to the same shape (round-7 lane-12 finding).
_VALID_REQUEST_ID = "00000000-0000-4000-8000-000000000abc"


def _valid_kwargs() -> dict[str, object]:
    return {
        "model": "gemma-4-e2b",
        "prompt_tokens": 12,
        "completion_tokens": 34,
        "request_id": _VALID_REQUEST_ID,
        "latency_ms": 250,
        "queue_wait_ms": 5,
        "finish_reason": "stop",
        "backend": "ollama",
    }


def test_response_metadata_constructs_with_all_eight_fields() -> None:
    meta = ResponseMetadata.model_validate(_valid_kwargs())
    assert meta.model == "gemma-4-e2b"
    assert meta.prompt_tokens == 12
    assert meta.completion_tokens == 34
    assert meta.request_id == _VALID_REQUEST_ID
    assert meta.latency_ms == 250
    assert meta.queue_wait_ms == 5
    assert meta.finish_reason == "stop"
    assert meta.backend == "ollama"


def test_response_metadata_rejects_non_uuid_request_id() -> None:
    """The schema-level UUID pattern is the round-7 defense-in-depth pin
    so a future code path building ResponseMetadata without going through
    the middleware-stamped UUID cannot ship a malformed correlation ID."""
    kwargs = _valid_kwargs()
    kwargs["request_id"] = "req-abc"
    with pytest.raises(ValidationError, match="request_id"):
        ResponseMetadata.model_validate(kwargs)


def test_response_metadata_rejects_oversize_model_name() -> None:
    """Mirrors InferenceRequest.model's 128-char cap — the same logical
    name flows in (request) and out (response), so the bounds must be
    symmetric."""
    kwargs = _valid_kwargs()
    kwargs["model"] = "x" * 129
    with pytest.raises(ValidationError, match="model"):
        ResponseMetadata.model_validate(kwargs)


@pytest.mark.parametrize(
    "field",
    [
        "model",
        "prompt_tokens",
        "completion_tokens",
        "request_id",
        "latency_ms",
        "queue_wait_ms",
        "finish_reason",
        "backend",
    ],
)
def test_response_metadata_requires_every_field(field: str) -> None:
    kwargs = _valid_kwargs()
    del kwargs[field]
    with pytest.raises(ValidationError, match=field):
        ResponseMetadata.model_validate(kwargs)


@pytest.mark.parametrize(
    "finish_reason",
    ["stop", "length", "timeout"],
)
def test_response_metadata_accepts_each_allowed_finish_reason(finish_reason: str) -> None:
    kwargs = _valid_kwargs()
    kwargs["finish_reason"] = finish_reason
    meta = ResponseMetadata.model_validate(kwargs)
    assert meta.finish_reason == finish_reason


def test_response_metadata_rejects_invalid_finish_reason() -> None:
    kwargs = _valid_kwargs()
    kwargs["finish_reason"] = "bad"
    with pytest.raises(ValidationError, match="finish_reason"):
        ResponseMetadata.model_validate(kwargs)


def test_response_metadata_rejects_unknown_field() -> None:
    kwargs = _valid_kwargs()
    kwargs["bogus"] = "x"
    with pytest.raises(ValidationError, match="extra"):
        ResponseMetadata.model_validate(kwargs)
