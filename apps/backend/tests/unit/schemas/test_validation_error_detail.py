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
    with pytest.raises(ValidationError, match="extra"):
        ValidationErrorDetail.model_validate(
            {"field": "x", "reason": "y", "severity": "critical"},
        )


@pytest.mark.parametrize(
    ("kwargs", "missing_key"),
    [
        pytest.param({"field": "x"}, "reason", id="missing-reason"),
        pytest.param({"reason": "x"}, "field", id="missing-field"),
    ],
)
def test_validation_error_detail_requires_both_fields(
    kwargs: dict[str, str], missing_key: str
) -> None:
    """Both fields are required — neither alone validates. Bind the parametrize id
    via ``exc_info`` so each iteration asserts the right boundary fired."""
    with pytest.raises(ValidationError) as exc_info:
        ValidationErrorDetail.model_validate(kwargs)
    assert missing_key in str(exc_info.value)
