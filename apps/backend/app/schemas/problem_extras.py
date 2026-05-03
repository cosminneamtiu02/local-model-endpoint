"""ProblemExtras — typed extension keys layered on top of ProblemDetails."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.validation_error_detail import ValidationErrorDetail


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
    in a multi-field response).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    validation_errors: list[ValidationErrorDetail] | None = Field(
        default=None,
        description="Per-field validation errors when status=422.",
    )
