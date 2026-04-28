"""ValidationErrorDetail — one entry inside the ``validation_errors`` extension.

RFC 7807 has no standard validation-error field, so VALIDATION_FAILED responses
extend the body with a ``validation_errors`` array of these objects.
"""

from pydantic import BaseModel, ConfigDict


class ValidationErrorDetail(BaseModel):
    """A single validation error — one field that failed Pydantic validation."""

    model_config = ConfigDict(extra="forbid")

    field: str
    reason: str
