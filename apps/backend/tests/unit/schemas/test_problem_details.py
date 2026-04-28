"""Unit tests for the RFC 7807 ProblemDetails schema."""

import json

import pytest
from pydantic import ValidationError

from app.schemas import ProblemDetails, ProblemExtras


def _base_kwargs() -> dict[str, object]:
    return {
        "type": "urn:lip:error:queue-full",
        "title": "Inference Queue Full",
        "status": 503,
        "detail": "Inference queue at capacity (5 waiters, max 4).",
        "instance": "/api/v1/inference",
        "code": "QUEUE_FULL",
        # UUID-shaped to match the schema's defense-in-depth pattern; the
        # handler always populates this field from the middleware's
        # generated UUID, so test fixtures should mirror the real wire shape.
        "request_id": "12345678-1234-1234-1234-123456789012",
    }


def test_problem_details_accepts_canonical_rfc7807_fields() -> None:
    """All five RFC 7807 fields plus code + request_id construct cleanly."""
    pd = ProblemDetails(**_base_kwargs())
    assert pd.type == "urn:lip:error:queue-full"
    assert pd.title == "Inference Queue Full"
    assert pd.status == 503
    assert pd.detail.startswith("Inference queue")
    assert pd.instance == "/api/v1/inference"
    assert pd.code == "QUEUE_FULL"
    assert pd.request_id == "12345678-1234-1234-1234-123456789012"


def test_problem_details_allows_arbitrary_extension_fields() -> None:
    """extra='allow' accepts typed-params extensions and validation_errors[]."""
    pd = ProblemDetails(
        **_base_kwargs(),
        max_waiters=4,
        current_waiters=5,
    )
    dumped = pd.model_dump()
    assert dumped["max_waiters"] == 4
    assert dumped["current_waiters"] == 5


def test_problem_details_accepts_validation_errors_extension_list() -> None:
    """validation_errors[] is permitted via extra='allow' as a list of dicts."""
    pd = ProblemDetails(
        **_base_kwargs(),
        validation_errors=[
            {"field": "messages.0.role", "reason": "Input should be 'user'"},
            {"field": "messages.1.content", "reason": "field required"},
        ],
    )
    dumped = pd.model_dump()
    assert isinstance(dumped["validation_errors"], list)
    assert dumped["validation_errors"][0]["field"] == "messages.0.role"
    assert dumped["validation_errors"][1]["reason"] == "field required"


def test_problem_details_rejects_missing_status() -> None:
    """status is required (RFC 7807 §3.1)."""
    kwargs = _base_kwargs()
    del kwargs["status"]
    with pytest.raises(ValidationError):
        ProblemDetails(**kwargs)


def test_problem_details_rejects_status_out_of_range() -> None:
    """status must be 400-599 — non-error responses are not problems."""
    kwargs = _base_kwargs()
    kwargs["status"] = 200
    with pytest.raises(ValidationError):
        ProblemDetails(**kwargs)


def test_problem_details_dump_includes_extension_fields_at_root() -> None:
    """extra fields appear at root level of model_dump(), not nested."""
    pd = ProblemDetails(**_base_kwargs(), validation_errors=[{"field": "x", "reason": "y"}])
    dumped = pd.model_dump()
    assert "validation_errors" in dumped
    assert dumped["validation_errors"] == [{"field": "x", "reason": "y"}]
    # No nested 'extra' key
    assert "extra" not in dumped
    assert "__pydantic_extra__" not in dumped


def test_problem_details_model_dump_json_produces_valid_json() -> None:
    """model_dump_json() — the path used by the handler — round-trips through json.loads."""
    pd = ProblemDetails(
        **_base_kwargs(),
        max_waiters=4,
        current_waiters=5,
        validation_errors=[{"field": "x", "reason": "y"}],
    )
    raw = pd.model_dump_json()
    parsed = json.loads(raw)
    assert parsed["status"] == 503
    assert parsed["max_waiters"] == 4
    assert parsed["validation_errors"] == [{"field": "x", "reason": "y"}]


def test_problem_extras_typed_dict_describes_validation_errors_extension() -> None:
    """ProblemExtras (TypedDict) documents the allowed extension keys.

    A TypedDict is a typing surface; it doesn't validate at runtime in vanilla
    Python. The most we can assert is that it's importable and that
    constructing one with the documented key shape doesn't raise.
    """
    extras: ProblemExtras = {
        "validation_errors": [
            # ValidationErrorDetail-shaped dicts (TypedDict accepts the model
            # at the type-check level; the runtime payload is just a list).
        ],
    }
    assert "validation_errors" in extras
    assert extras["validation_errors"] == []
