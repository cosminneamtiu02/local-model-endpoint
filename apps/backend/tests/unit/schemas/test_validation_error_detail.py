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
        ValidationErrorDetail.model_validate(
            {"field": "x", "reason": "y", "severity": "critical"},
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"field": "x"}, id="missing-reason"),
        pytest.param({"reason": "x"}, id="missing-field"),
    ],
)
def test_validation_error_detail_requires_both_fields(kwargs: dict[str, str]) -> None:
    """Both fields are required — neither alone validates."""
    with pytest.raises(ValidationError):
        ValidationErrorDetail.model_validate(kwargs)
