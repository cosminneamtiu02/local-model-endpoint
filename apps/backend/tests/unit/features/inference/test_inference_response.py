"""Unit tests for InferenceResponse (LIP-E001-F001)."""

import pytest
from pydantic import ValidationError

from app.features.inference.schemas.inference_response import InferenceResponse
from app.features.inference.schemas.response_metadata import ResponseMetadata


def _valid_metadata() -> ResponseMetadata:
    return ResponseMetadata(
        model="gemma-4-e2b",
        prompt_tokens=12,
        completion_tokens=34,
        request_id="req-abc",
        latency_ms=250,
        queue_wait_ms=5,
        finish_reason="stop",
        backend="ollama",
    )


def test_inference_response_constructs_with_content_and_metadata() -> None:
    resp = InferenceResponse(content="hello world", metadata=_valid_metadata())
    assert resp.content == "hello world"
    assert resp.metadata.model == "gemma-4-e2b"


def test_inference_response_rejects_unknown_top_level_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        InferenceResponse.model_validate(
            {
                "content": "x",
                "metadata": _valid_metadata().model_dump(),
                "stream": True,
            },
        )


def test_inference_response_propagates_metadata_validation_errors() -> None:
    valid = _valid_metadata().model_dump()
    valid["finish_reason"] = "bad"
    with pytest.raises(ValidationError, match="finish_reason"):
        InferenceResponse.model_validate({"content": "x", "metadata": valid})


def test_inference_response_requires_metadata() -> None:
    with pytest.raises(ValidationError, match="metadata"):
        InferenceResponse.model_validate({"content": "x"})


def test_inference_response_requires_content() -> None:
    with pytest.raises(ValidationError, match="content"):
        InferenceResponse.model_validate({"metadata": _valid_metadata().model_dump()})


@pytest.mark.parametrize(
    "missing_field",
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
def test_inference_response_propagates_missing_metadata_field_errors(missing_field: str) -> None:
    metadata = _valid_metadata().model_dump()
    del metadata[missing_field]
    with pytest.raises(ValidationError, match=missing_field):
        InferenceResponse.model_validate({"content": "x", "metadata": metadata})
