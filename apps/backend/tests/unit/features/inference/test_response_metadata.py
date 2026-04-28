"""Unit tests for ResponseMetadata (LIP-E001-F001)."""

import pytest
from pydantic import ValidationError

from app.features.inference.schemas.response_metadata import ResponseMetadata


def _valid_kwargs() -> dict[str, object]:
    return {
        "model": "gemma-4-e2b",
        "prompt_tokens": 12,
        "completion_tokens": 34,
        "request_id": "req-abc",
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
    assert meta.request_id == "req-abc"
    assert meta.latency_ms == 250
    assert meta.queue_wait_ms == 5
    assert meta.finish_reason == "stop"
    assert meta.backend == "ollama"


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
