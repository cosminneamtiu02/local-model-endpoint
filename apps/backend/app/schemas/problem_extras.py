"""ProblemExtras — typed extension keys layered on top of ProblemDetails."""

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from app.schemas.validation_error_detail import ValidationErrorDetail


class ProblemExtras(TypedDict, total=False):
    """Allowed extension keys layered on top of ProblemDetails.

    The exception handler spreads these keys at root level on the problem+json
    body. ``total=False`` because every key is optional — only
    ``VALIDATION_FAILED`` populates ``validation_errors``.

    ``validation_errors`` carries :class:`ValidationErrorDetail` model instances
    (not dumped dicts): Pydantic walks the tree at ``model_dump_json`` time
    and serializes them once at the wire boundary, instead of paying a
    construction-then-dump roundtrip per error in the handler. Consumers
    should treat that array as canonical and ignore root-level ``field`` /
    ``reason`` (which reflect only the first error in a multi-field response).
    """

    validation_errors: list["ValidationErrorDetail"]
