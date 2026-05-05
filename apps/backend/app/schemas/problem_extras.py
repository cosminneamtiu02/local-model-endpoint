"""ProblemExtras — typed extension keys layered on top of ProblemDetails."""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.validation_error_detail import ValidationErrorDetail

VALIDATION_ERRORS_MAX_LENGTH: Final[int] = 64
"""Cap on the number of per-field entries in ``ProblemExtras.validation_errors``.

Per-entry caps (``FIELD_MAX_CHARS=512``, ``REASON_MAX_CHARS=2048``) bound the
size of ONE entry, but without a list-length cap a pathological consumer
posting a request that fails N validators (e.g. a 10000-element array of
malformed items) could amplify the response into a multi-MB body. 64 is a
generous practical ceiling — a Pydantic schema with more than 64 distinct
failures in one request indicates either a fundamentally malformed payload
(no per-field detail past the first 64 is operator-actionable) or an upstream
abuse vector. The handler truncates at construction so the wire body stays
bounded; consumers receive the first 64 errors.
"""


class ProblemExtras(BaseModel):
    """Typed root-level extension fields for ProblemDetails (RFC 7807 §3.2).

    The exception handler spreads these fields at root level on the
    problem+json body via ``model_dump(exclude_none=True)``. Every field
    is optional — only ``VALIDATION_FAILED`` populates ``validation_errors``
    today.

    ``validation_errors`` carries :class:`ValidationErrorDetail` model
    instances (not dumped dicts): Pydantic walks the tree at
    ``model_dump_json`` time and serializes them once at the wire boundary,
    instead of paying a construction-then-dump roundtrip per error in the
    handler. Consumers should treat that array as canonical and ignore
    root-level ``field`` / ``reason`` (which reflect only the first error
    in a multi-field response). The list is capped at
    ``VALIDATION_ERRORS_MAX_LENGTH`` entries — see that constant's docstring
    for the response-amplification rationale.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    validation_errors: list[ValidationErrorDetail] | None = Field(
        default=None,
        max_length=VALIDATION_ERRORS_MAX_LENGTH,
        description="Per-field validation errors when status=422 (capped at 64 entries).",
    )
