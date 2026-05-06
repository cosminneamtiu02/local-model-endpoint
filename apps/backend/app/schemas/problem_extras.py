"""ProblemExtras — typed extension keys layered on top of ProblemDetails."""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.validation_error_detail import ValidationErrorDetail

VALIDATION_ERRORS_MAX_LENGTH: Final[int] = 64
"""Cap on the number of per-field entries in ``ProblemExtras.validation_errors``.

Per-entry caps (``FIELD_MAX_CHARS=512``, ``REASON_MAX_CHARS=2048``) bound the
size of ONE entry, but without a list-length cap a pathological consumer
posting a request that fails N validators (e.g. a 10_000-element array of
malformed items) could amplify the response into a multi-MB body. 64 is a
generous practical ceiling — a Pydantic schema with more than 64 distinct
failures in one request indicates either a fundamentally malformed payload
(no per-field detail past the first 64 is operator-actionable) or an upstream
abuse vector. The validation handler slices ``raw_errors`` at this cap
BEFORE constructing ``ValidationErrorDetail`` entries, so consumers receive
the first 64 errors and the ``detail`` field names the truncation
("Validation failed for N fields (first 64 included)") when N exceeded the
cap. The schema-side ``max_length`` here is the belt-and-suspenders ceiling
that surfaces a regression if the handler-side slice ever drifts.
"""


class ProblemExtras(BaseModel):
    """Typed root-level extension fields for ProblemDetails (RFC 7807 §3.2).

    The exception handler spreads these fields at root level on the
    problem+json body via ``model_dump(exclude_none=True)``. Every field
    is optional — only ``VALIDATION_FAILED`` populates ``validation_errors``
    today.

    ``validation_errors`` is typed as ``list[ValidationErrorDetail]``;
    inside ``_build_problem_payload`` the handler calls
    ``extras.model_dump(mode="python", exclude_none=True)`` which Pydantic
    walks recursively, converting each entry to a plain dict before the
    spread reaches ``ProblemDetails(**extras_widened)``. ``model_dump_json``
    on the resulting ProblemDetails then serializes those dicts as the
    final wire body. Consumers should treat the array as canonical and
    ignore root-level ``field`` / ``reason`` (which reflect only the first
    error in a multi-field response). The list is soft-truncated by the
    handler at ``VALIDATION_ERRORS_MAX_LENGTH`` entries (the ``detail``
    field names the truncation when it kicks in); the schema ``max_length``
    is a belt-and-suspenders ceiling — see that constant's docstring for
    the response-amplification rationale.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    validation_errors: list[ValidationErrorDetail] | None = Field(
        default=None,
        max_length=VALIDATION_ERRORS_MAX_LENGTH,
        description="Per-field validation errors when status=422 (capped at 64 entries).",
    )
