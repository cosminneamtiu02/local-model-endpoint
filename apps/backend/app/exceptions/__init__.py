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
from app.exceptions.base import DomainError

__all__ = [
    "ConflictError",
    "DomainError",
    "InternalError",
    "NotFoundError",
    "RateLimitedError",
    "RateLimitedParams",
    "ValidationFailedError",
    "ValidationFailedParams",
]
