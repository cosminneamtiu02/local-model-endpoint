"""Tests for generated domain error classes."""

from app.exceptions import RateLimitedError


def test_domain_error_constructs_with_typed_params() -> None:
    """Generated DomainError subclass should construct with correct code, status, and params."""
    error = RateLimitedError(retry_after_seconds=60)

    assert error.code == "RATE_LIMITED"
    assert error.http_status == 429
    assert error.params is not None
    assert error.params.model_dump() == {"retry_after_seconds": 60}
    assert "RATE_LIMITED" in str(error)
