"""ProblemExtras — typed extension keys layered on top of ProblemDetails."""

from typing import TypedDict

from app.schemas.validation_error_detail import ValidationErrorDetail


class ProblemExtras(TypedDict, total=False):
    """Allowed extension keys layered on top of ProblemDetails.

    Used by ``app.api.errors._build_problem_payload`` to type the ``extras``
    parameter instead of ``dict[str, Any]``. ``total=False`` because every key
    is optional — only ``VALIDATION_FAILED`` populates ``validation_errors``.

    The handler at ``app.api.errors._handle_validation_error`` populates
    ``validation_errors`` with the full per-field detail array; consumers
    should treat that array as canonical and ignore root-level ``field`` /
    ``reason`` (which reflect only the first error in a multi-field response).
    """

    validation_errors: list[ValidationErrorDetail]
