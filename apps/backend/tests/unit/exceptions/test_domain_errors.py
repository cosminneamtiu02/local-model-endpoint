"""Unit tests for the generated DomainError subclasses."""

from typing import Any

import pytest

from app.exceptions import (
    ConflictError,
    DomainError,
    InternalError,
    NotFoundError,
    RateLimitedError,
    RateLimitedParams,
    ValidationFailedError,
    ValidationFailedParams,
)


@pytest.mark.parametrize(
    ("error_class", "expected_code", "expected_status", "kwargs"),
    [
        pytest.param(NotFoundError, "NOT_FOUND", 404, {}, id="not_found"),
        pytest.param(ConflictError, "CONFLICT", 409, {}, id="conflict"),
        pytest.param(InternalError, "INTERNAL_ERROR", 500, {}, id="internal_error"),
        pytest.param(
            ValidationFailedError,
            "VALIDATION_FAILED",
            422,
            {"field": "email", "reason": "must be a valid email"},
            id="validation_failed",
        ),
        pytest.param(
            RateLimitedError,
            "RATE_LIMITED",
            429,
            {"retry_after_seconds": 60},
            id="rate_limited",
        ),
    ],
)
def test_domain_error_subclasses_carry_code_and_status(
    error_class: type[DomainError],
    expected_code: str,
    expected_status: int,
    kwargs: dict[str, Any],
) -> None:
    """Each generated error class exposes its code and http_status as ClassVars."""
    err = error_class(**kwargs)
    assert err.code == expected_code
    assert err.http_status == expected_status


def test_validation_failed_error_params_round_trip() -> None:
    """ValidationFailedError carries typed params accessible via model_dump."""
    err = ValidationFailedError(field="email", reason="must be a valid email")
    assert isinstance(err.params, ValidationFailedParams)
    assert err.params.model_dump() == {"field": "email", "reason": "must be a valid email"}


def test_rate_limited_error_params_round_trip() -> None:
    """RateLimitedError carries typed params accessible via model_dump."""
    err = RateLimitedError(retry_after_seconds=60)
    assert isinstance(err.params, RateLimitedParams)
    assert err.params.model_dump() == {"retry_after_seconds": 60}


def test_parameterless_errors_have_none_params() -> None:
    """NotFoundError and siblings have None for params."""
    assert NotFoundError().params is None
    assert ConflictError().params is None
    assert InternalError().params is None
