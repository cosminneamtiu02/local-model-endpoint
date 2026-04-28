"""Domain exception hierarchy.

Import errors from this module, never from _generated/ directly.
"""

from app.exceptions._generated import (
    AdapterConnectionFailureError,
    AdapterConnectionFailureParams,
    ConflictError,
    InferenceTimeoutError,
    InferenceTimeoutParams,
    InternalError,
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
from app.exceptions.base import DomainError

__all__ = [
    "AdapterConnectionFailureError",
    "AdapterConnectionFailureParams",
    "ConflictError",
    "DomainError",
    "InferenceTimeoutError",
    "InferenceTimeoutParams",
    "InternalError",
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
