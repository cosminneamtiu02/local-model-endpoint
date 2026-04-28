"""Domain exception hierarchy.

Import errors from this module, never from _generated/ directly.
"""

from app.exceptions._generated import (
    ConflictError,
    InternalError,
    NotFoundError,
    RateLimitedError,
    RateLimitedParams,
    ValidationFailedError,
    ValidationFailedParams,
)
from app.exceptions._generated._registry import ERROR_CLASSES
from app.exceptions.base import DomainError

__all__ = [
    "ERROR_CLASSES",
    "ConflictError",
    "DomainError",
    "InternalError",
    "NotFoundError",
    "RateLimitedError",
    "RateLimitedParams",
    "ValidationFailedError",
    "ValidationFailedParams",
]
