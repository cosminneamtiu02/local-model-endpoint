"""Domain exception hierarchy. See architecture/import-linter-contracts.ini."""

from app.exceptions._generated import (
    AdapterConnectionFailureError,
    AdapterConnectionFailureParams,
    ConflictError,
    HttpError,
    InferenceTimeoutError,
    InferenceTimeoutParams,
    InternalError,
    MethodNotAllowedError,
    ModelCapabilityNotSupportedError,
    ModelCapabilityNotSupportedParams,
    NotFoundError,
    QueueFullError,
    QueueFullParams,
    RateLimitedError,
    RateLimitedParams,
    RegistryNotFoundError,
    RegistryNotFoundParams,
    ValidationFailedError,
    ValidationFailedParams,
)
from app.exceptions._generated._registry import ERROR_CLASSES
from app.exceptions.base import DomainError

__all__ = [
    "ERROR_CLASSES",
    "AdapterConnectionFailureError",
    "AdapterConnectionFailureParams",
    "ConflictError",
    "DomainError",
    "HttpError",
    "InferenceTimeoutError",
    "InferenceTimeoutParams",
    "InternalError",
    "MethodNotAllowedError",
    "ModelCapabilityNotSupportedError",
    "ModelCapabilityNotSupportedParams",
    "NotFoundError",
    "QueueFullError",
    "QueueFullParams",
    "RateLimitedError",
    "RateLimitedParams",
    "RegistryNotFoundError",
    "RegistryNotFoundParams",
    "ValidationFailedError",
    "ValidationFailedParams",
]
