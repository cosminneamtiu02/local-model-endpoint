"""Unit tests for the RFC 7807 ProblemDetails schema."""

import pytest
from pydantic import ValidationError

from app.schemas import ProblemDetails


def _base_kwargs() -> dict[str, object]:
    return {
        "type": "urn:lip:error:queue-full",
        "title": "Inference Queue Full",
        "status": 503,
        "detail": "Inference queue at capacity (5 waiters, max 4).",
        "instance": "/api/v1/inference",
        "code": "QUEUE_FULL",
        "request_id": "abc-123",
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
    assert pd.request_id == "abc-123"


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
