"""Unit tests for InferenceResponse (LIP-E001-F001)."""

import pytest
from pydantic import ValidationError

from app.features.inference.schemas.inference_response import InferenceResponse
from app.features.inference.schemas.response_metadata import ResponseMetadata


def _valid_metadata(kwargs: dict[str, object]) -> ResponseMetadata:
    return ResponseMetadata.model_validate(kwargs)


def test_inference_response_constructs_with_content_and_metadata(
    valid_response_metadata_kwargs: dict[str, object],
) -> None:
    resp = InferenceResponse(
        content="hello world",
        metadata=_valid_metadata(valid_response_metadata_kwargs),
    )
    assert resp.content == "hello world"
    assert resp.metadata.model == "gemma-4-e2b"


def test_inference_response_rejects_unknown_top_level_field(
    valid_response_metadata_kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="extra"):
        InferenceResponse.model_validate(
            {
                "content": "x",
                "metadata": _valid_metadata(valid_response_metadata_kwargs).model_dump(),
                "stream": True,
            },
        )


def test_inference_response_propagates_metadata_validation_errors(
    valid_response_metadata_kwargs: dict[str, object],
) -> None:
    valid = _valid_metadata(valid_response_metadata_kwargs).model_dump()
    valid["finish_reason"] = "bad"
    # Anchor on the Literal-rejection message rather than the bare field
    # name. ``match="finish_reason"`` would also match an unrelated
    # missing-field error message that happens to mention the field; this
    # ``match=`` value pins the propagation specifically through the
    # nested validator that rejects the closed enum, so a future regression
    # that skipped the inner validator on the wrapping envelope would fail
    # the test.
    with pytest.raises(ValidationError, match=r"Input should be 'stop', 'length' or 'timeout'"):
        InferenceResponse.model_validate({"content": "x", "metadata": valid})


def test_inference_response_requires_metadata() -> None:
    # Anchor on Pydantic v2's missing-required-field message rather than
    # the bare field name. ``match="metadata"`` would also match a nested
    # ``metadata.finish_reason`` chain error from sibling regressions
    # (and the validator-propagation test above already covers that
    # case). ``(?s)`` enables DOTALL so ``.`` traverses Pydantic's
    # ``\n``-separated error rendering.
    with pytest.raises(ValidationError, match=r"(?s)metadata.*Field required"):
        InferenceResponse.model_validate({"content": "x"})


def test_inference_response_requires_content(
    valid_response_metadata_kwargs: dict[str, object],
) -> None:
    # Same regex-tightness rationale as the metadata sibling above.
    with pytest.raises(ValidationError, match=r"(?s)content.*Field required"):
        InferenceResponse.model_validate(
            {"metadata": _valid_metadata(valid_response_metadata_kwargs).model_dump()},
        )


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
def test_inference_response_propagates_missing_metadata_field_errors(
    valid_response_metadata_kwargs: dict[str, object],
    missing_field: str,
) -> None:
    metadata = _valid_metadata(valid_response_metadata_kwargs).model_dump()
    del metadata[missing_field]
    with pytest.raises(ValidationError, match=missing_field):
        InferenceResponse.model_validate({"content": "x", "metadata": metadata})
