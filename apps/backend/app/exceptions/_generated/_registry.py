"""Generated error registry. Do not edit."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.exceptions.base import DomainError

from app.exceptions._generated.conflict_error import ConflictError
from app.exceptions._generated.internal_error import InternalError
from app.exceptions._generated.not_found_error import NotFoundError
from app.exceptions._generated.rate_limited_error import RateLimitedError
from app.exceptions._generated.validation_failed_error import ValidationFailedError

ERROR_CLASSES: dict[str, type[DomainError]] = {
    "CONFLICT": ConflictError,
    "INTERNAL_ERROR": InternalError,
    "NOT_FOUND": NotFoundError,
    "RATE_LIMITED": RateLimitedError,
    "VALIDATION_FAILED": ValidationFailedError,
}
