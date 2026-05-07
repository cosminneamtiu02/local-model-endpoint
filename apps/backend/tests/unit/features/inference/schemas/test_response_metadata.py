"""Unit tests for ResponseMetadata (LIP-E001-F001)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.features.inference.model.dos_caps import MODEL_NAME_MAX_CHARS
from app.features.inference.schemas.response_metadata import ResponseMetadata
from tests.unit.features.inference.conftest import VALID_REQUEST_ID


def test_response_metadata_constructs_with_all_eight_fields(
    valid_response_metadata_kwargs: dict[str, object],
) -> None:
    meta = ResponseMetadata.model_validate(valid_response_metadata_kwargs)
    assert meta.model == "gemma-4-e2b"
    assert meta.prompt_tokens == 12
    assert meta.completion_tokens == 34
    assert meta.request_id == VALID_REQUEST_ID
    assert meta.latency_ms == 250
    assert meta.queue_wait_ms == 5
    assert meta.finish_reason == "stop"
    assert meta.backend == "ollama"


# Each parametrize id documents the specific mutation type — UUID
# validation, length cap, enum membership, extra=forbid — so a
# failure points at the precise validator that fired. Per-case
# rationale notes inline rather than per-test docstrings since the id
# encodes the discrimination.
@pytest.mark.parametrize(
    ("mutation_key", "mutation_value", "expected_match"),
    [
        # UUID-shape defense-in-depth: a future code path constructing
        # ResponseMetadata without the middleware-stamped UUID cannot
        # ship a malformed correlation id.
        pytest.param("request_id", "req-abc", "request_id", id="non-uuid-request-id"),
        # MODEL_NAME_MAX_CHARS cap: same logical name flows in
        # (InferenceRequest) and out (ResponseMetadata), so the bound
        # must be symmetric.
        pytest.param("model", "x" * (MODEL_NAME_MAX_CHARS + 1), "model", id="oversize-model-name"),
        # Closed-alphabet finish_reason: enum membership.
        pytest.param("finish_reason", "bad", "finish_reason", id="invalid-finish-reason"),
        # extra="forbid": a future schema drift must not let unknown
        # keys ride in via the boundary.
        pytest.param("bogus", "x", "extra", id="unknown-field"),
    ],
)
def test_response_metadata_rejects_invalid_field_value(
    valid_response_metadata_kwargs: dict[str, object],
    mutation_key: str,
    mutation_value: object,
    expected_match: str,
) -> None:
    """ResponseMetadata's per-field validators reject invalid mutations."""
    kwargs = dict(valid_response_metadata_kwargs)
    kwargs[mutation_key] = mutation_value
    with pytest.raises(ValidationError, match=expected_match):
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


# ``test_response_metadata_rejects_invalid_finish_reason`` and
# ``test_response_metadata_rejects_unknown_field`` were absorbed into
# ``test_response_metadata_rejects_invalid_field_value`` (the
# ``invalid-finish-reason`` and ``unknown-field`` parametrize ids). The
# specific rationales now live in inline comments next to each
# ``pytest.param`` row, so a per-id failure still surfaces the right
# discrimination.
