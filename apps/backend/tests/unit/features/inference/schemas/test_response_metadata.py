"""Unit tests for ResponseMetadata (LIP-E001-F001)."""

import pytest
from pydantic import ValidationError

from app.features.inference.schemas.response_metadata import ResponseMetadata


def test_response_metadata_constructs_with_all_eight_fields(
    valid_response_metadata_kwargs: dict[str, object],
    valid_request_id: str,
) -> None:
    meta = ResponseMetadata.model_validate(valid_response_metadata_kwargs)
    assert meta.model == "gemma-4-e2b"
    assert meta.prompt_tokens == 12
    assert meta.completion_tokens == 34
    assert meta.request_id == valid_request_id
    assert meta.latency_ms == 250
    assert meta.queue_wait_ms == 5
    assert meta.finish_reason == "stop"
    assert meta.backend == "ollama"


def test_response_metadata_rejects_non_uuid_request_id(
    valid_response_metadata_kwargs: dict[str, object],
) -> None:
    """The schema-level UUID pattern is defense-in-depth: a future code
    path building ResponseMetadata without going through the
    middleware-stamped UUID cannot ship a malformed correlation ID."""
    kwargs = dict(valid_response_metadata_kwargs)
    kwargs["request_id"] = "req-abc"
    with pytest.raises(ValidationError, match="request_id"):
        ResponseMetadata.model_validate(kwargs)


def test_response_metadata_rejects_oversize_model_name(
    valid_response_metadata_kwargs: dict[str, object],
) -> None:
    """Mirrors InferenceRequest.model's MODEL_NAME_MAX_LENGTH-char cap — the
    same logical name flows in (request) and out (response), so the bounds
    must be symmetric. Deriving the oversize length from the source-of-
    truth constant means a future cap bump only needs to change one site."""
    from app.features.inference.model.caps import MODEL_NAME_MAX_LENGTH

    kwargs = dict(valid_response_metadata_kwargs)
    kwargs["model"] = "x" * (MODEL_NAME_MAX_LENGTH + 1)
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
def test_response_metadata_requires_every_field(
    valid_response_metadata_kwargs: dict[str, object],
    field: str,
) -> None:
    kwargs = dict(valid_response_metadata_kwargs)
    del kwargs[field]
    with pytest.raises(ValidationError, match=field):
        ResponseMetadata.model_validate(kwargs)


@pytest.mark.parametrize(
    "finish_reason",
    ["stop", "length", "timeout"],
)
def test_response_metadata_accepts_each_allowed_finish_reason(
    valid_response_metadata_kwargs: dict[str, object],
    finish_reason: str,
) -> None:
    kwargs = dict(valid_response_metadata_kwargs)
    kwargs["finish_reason"] = finish_reason
    meta = ResponseMetadata.model_validate(kwargs)
    assert meta.finish_reason == finish_reason


def test_response_metadata_rejects_invalid_finish_reason(
    valid_response_metadata_kwargs: dict[str, object],
) -> None:
    kwargs = dict(valid_response_metadata_kwargs)
    kwargs["finish_reason"] = "bad"
    with pytest.raises(ValidationError, match="finish_reason"):
        ResponseMetadata.model_validate(kwargs)


def test_response_metadata_rejects_unknown_field(
    valid_response_metadata_kwargs: dict[str, object],
) -> None:
    kwargs = dict(valid_response_metadata_kwargs)
    kwargs["bogus"] = "x"
    with pytest.raises(ValidationError, match="extra"):
        ResponseMetadata.model_validate(kwargs)
