"""Verifies the generated _registry.ERROR_CLASSES exposes every error code."""

from __future__ import annotations

from app.exceptions import (
    ERROR_CLASSES,
    AdapterConnectionFailureError,
    ConflictError,
    DomainError,
    InferenceTimeoutError,
    InternalError,
    MethodNotAllowedError,
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
    REGISTRY_NOT_FOUND, MODEL_CAPABILITY_NOT_SUPPORTED) plus one HTTP-status
    code added for ``_handle_http_exception`` source-of-truth alignment
    (METHOD_NOT_ALLOWED). The wire ``code: "HTTP_ERROR"`` ships from a
    string literal in ``_http_code_for_status`` for the generic-4xx
    framework path; there is no DomainError class for it.
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
        "METHOD_NOT_ALLOWED": MethodNotAllowedError,
    }
    assert expected == ERROR_CLASSES


def test_registry_classes_are_domain_error_subclasses() -> None:
    """Every class in the registry is a DomainError subclass."""
    for code, cls in ERROR_CLASSES.items():
        assert issubclass(cls, DomainError), f"{code} -> {cls} is not a DomainError"


def test_registry_lookup_for_unknown_code_returns_none() -> None:
    """``ERROR_CLASSES.get(unknown_code)`` returns None — the documented
    contract for the consumer-fallback pattern. Pinning the contract so a
    future maintainer who consolidates ``_http_code_for_status`` against
    this lookup has a stable behavior to lean on."""
    assert ERROR_CLASSES.get("NEVER_DECLARED_CODE") is None
    assert ERROR_CLASSES.get("") is None


def test_registry_type_uri_matches_problem_details_pattern() -> None:
    """Every ``cls.type_uri`` matches the same regex ``ProblemDetails.type``
    enforces — build-time guard so a future codegen change that emits a
    non-conforming URN (e.g. mixed-case, disallowed characters) fails at
    test time rather than as a request-time ValidationError that ships a
    bare 500 to the consumer.
    """
    import re

    from app.schemas.problem_details import ProblemDetails

    # ProblemDetails.type carries the canonical pattern as a Field
    # constraint; pull it out via model_fields metadata so the test stays
    # in lockstep with the schema.
    field = ProblemDetails.model_fields["type"]
    pattern_str: str | None = None
    for meta in field.metadata:
        candidate = getattr(meta, "pattern", None)
        if isinstance(candidate, str):
            pattern_str = candidate
            break
    assert pattern_str is not None, "ProblemDetails.type must declare a pattern"
    pattern = re.compile(pattern_str)
    for code, cls in ERROR_CLASSES.items():
        assert pattern.match(cls.type_uri), (
            f"{code} -> type_uri={cls.type_uri!r} does not match "
            f"ProblemDetails.type pattern {pattern_str!r}"
        )
