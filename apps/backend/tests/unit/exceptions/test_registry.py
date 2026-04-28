"""Verifies the generated _registry.ERROR_CLASSES exposes every error code."""

from app.exceptions import (
    ERROR_CLASSES,
    ConflictError,
    DomainError,
    InternalError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)


def test_registry_contains_all_five_canonical_error_codes() -> None:
    """ERROR_CLASSES dict maps every code in errors.yaml to its class."""
    expected = {
        "NOT_FOUND": NotFoundError,
        "CONFLICT": ConflictError,
        "VALIDATION_FAILED": ValidationFailedError,
        "INTERNAL_ERROR": InternalError,
        "RATE_LIMITED": RateLimitedError,
    }
    assert expected == ERROR_CLASSES


def test_registry_classes_are_domain_error_subclasses() -> None:
    """Every class in the registry is a DomainError subclass."""
    for code, cls in ERROR_CLASSES.items():
        assert issubclass(cls, DomainError), f"{code} -> {cls} is not a DomainError"
