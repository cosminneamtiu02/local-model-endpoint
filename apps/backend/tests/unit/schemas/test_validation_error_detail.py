"""Unit tests for the ValidationErrorDetail schema."""

import pytest
from pydantic import ValidationError

from app.schemas import ValidationErrorDetail


def test_validation_error_detail_constructs_with_field_and_reason() -> None:
    detail = ValidationErrorDetail(
        field="messages.0.role",
        reason="Input should be 'user', 'assistant' or 'system'",
    )
    assert detail.field == "messages.0.role"
    assert "user" in detail.reason


def test_validation_error_detail_rejects_unknown_keys() -> None:
    """extra='forbid' on the validation array entries (input-side discipline)."""
    with pytest.raises(ValidationError):
        ValidationErrorDetail(
            field="x",
            reason="y",
            severity="critical",  # pyright: ignore[reportCallIssue]
        )


def test_validation_error_detail_requires_both_fields() -> None:
    with pytest.raises(ValidationError):
        ValidationErrorDetail(field="x")  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValidationError):
        ValidationErrorDetail(reason="x")  # pyright: ignore[reportCallIssue]
