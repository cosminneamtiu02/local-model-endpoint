"""ValidationErrorDetail — one entry inside the ``validation_errors`` extension.

The RFC 7807 ``ProblemDetails`` shape has no standard validation-error field,
so VALIDATION_FAILED responses extend the body with a ``validation_errors``
array of these objects, one per failed field. Renamed from the bootstrap
``error_detail`` so the file name matches the class purpose (the original
``detail`` was overloaded with RFC 7807's ``detail`` summary string).
"""

from pydantic import BaseModel, ConfigDict


class ValidationErrorDetail(BaseModel):
    """A single validation error — one field that failed Pydantic validation."""

    model_config = ConfigDict(extra="forbid")

    field: str
    reason: str
