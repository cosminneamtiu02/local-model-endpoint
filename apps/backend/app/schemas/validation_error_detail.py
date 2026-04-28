"""ValidationErrorDetail — one entry inside the ``validation_errors`` extension.

RFC 7807 has no standard validation-error field, so VALIDATION_FAILED responses
extend the body with a ``validation_errors`` array of these objects.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

# Bound the reflected-input surface in 422 responses: Pydantic's `error["msg"]`
# can interpolate the entire offending value, and `loc` paths can be deeply
# nested. Caps mirror the per-field `max_length` discipline applied to every
# request schema (defense against unbounded response amplification). Public
# so the exception handler can truncate at the edge before construction.
FIELD_MAX_CHARS: Final[int] = 512
REASON_MAX_CHARS: Final[int] = 2048


class ValidationErrorDetail(BaseModel):
    """A single validation error — one field that failed Pydantic validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(max_length=FIELD_MAX_CHARS)
    reason: str = Field(max_length=REASON_MAX_CHARS)
