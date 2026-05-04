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

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    # ``min_length=1`` mirrors the sibling-string-field discipline across
    # the wire schemas (ProblemDetails.title, ProblemDetails.detail,
    # ResponseMetadata.model). The exception handler always populates
    # these from non-empty Pydantic error data; the floor catches
    # hand-constructed test fixtures or future helpers that could ship
    # ``field=""`` and pass schema validation.
    field: str = Field(min_length=1, max_length=FIELD_MAX_CHARS)
    reason: str = Field(min_length=1, max_length=REASON_MAX_CHARS)
