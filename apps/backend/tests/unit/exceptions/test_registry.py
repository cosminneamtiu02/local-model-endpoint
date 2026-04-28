"""Verifies the generated _registry.ERROR_CLASSES exposes every error code."""

from app.exceptions import (
    ERROR_CLASSES,
    AdapterConnectionFailureError,
    ConflictError,
    DomainError,
    InferenceTimeoutError,
    InternalError,
    ModelCapabilityNotSupportedError,
    NotFoundError,
    QueueFullError,
    RateLimitedError,
    RegistryNotFoundError,
    ValidationFailedError,
)


def test_registry_contains_all_canonical_error_codes() -> None:
    """ERROR_CLASSES dict maps every code in errors.yaml to its class.

    Five generic codes (NOT_FOUND, CONFLICT, VALIDATION_FAILED, INTERNAL_ERROR,
    RATE_LIMITED) plus five LIP-specific codes added by LIP-E004-F004
    (QUEUE_FULL, INFERENCE_TIMEOUT, ADAPTER_CONNECTION_FAILURE,
    REGISTRY_NOT_FOUND, MODEL_CAPABILITY_NOT_SUPPORTED).
    """
    expected = {
        "NOT_FOUND": NotFoundError,
        "CONFLICT": ConflictError,
        "VALIDATION_FAILED": ValidationFailedError,
        "INTERNAL_ERROR": InternalError,
        "RATE_LIMITED": RateLimitedError,
        "QUEUE_FULL": QueueFullError,
        "INFERENCE_TIMEOUT": InferenceTimeoutError,
        "ADAPTER_CONNECTION_FAILURE": AdapterConnectionFailureError,
        "REGISTRY_NOT_FOUND": RegistryNotFoundError,
        "MODEL_CAPABILITY_NOT_SUPPORTED": ModelCapabilityNotSupportedError,
    }
    assert expected == ERROR_CLASSES


def test_registry_classes_are_domain_error_subclasses() -> None:
    """Every class in the registry is a DomainError subclass."""
    for code, cls in ERROR_CLASSES.items():
        assert issubclass(cls, DomainError), f"{code} -> {cls} is not a DomainError"
