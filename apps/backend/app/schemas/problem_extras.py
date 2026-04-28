"""ProblemExtras — typed extension keys layered on top of ProblemDetails."""

from typing import Any, TypedDict


class ProblemExtras(TypedDict, total=False):
    """Allowed extension keys layered on top of ProblemDetails.

    The exception handler spreads these keys at root level on the problem+json
    body. ``total=False`` because every key is optional — only
    ``VALIDATION_FAILED`` populates ``validation_errors``.

    ``validation_errors`` is typed as ``list[dict[str, Any]]`` (the dumped
    form) rather than ``list[ValidationErrorDetail]`` because the handler
    runs ``ValidationErrorDetail.model_dump(mode="json")`` before placing
    the array here, and the spread operator passes the dict shape into
    ProblemDetails. Consumers should treat that array as canonical and
    ignore root-level ``field`` / ``reason`` (which reflect only the first
    error in a multi-field response).
    """

    validation_errors: list[dict[str, Any]]
