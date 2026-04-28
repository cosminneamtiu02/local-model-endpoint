"""Health endpoint — mounted at root, outside /v1/.

Liveness only in v1. Readiness will be added by LIP-E006-F001 when the
warm-up signal from LIP-E005-F001 is wired during feature-dev.

The ``responses={"default": ...}`` argument documents that ANY error response
from this route — and from any route in this app — follows the
:class:`ProblemDetails` (RFC 7807 ``application/problem+json``) shape. The
``"default"`` key is normalized by FastAPI to OpenAPI's default-response
convention, which is the truthful match for "the global exception handler
in ``app/api/errors.py`` runs against every status code we don't enumerate".
Listing ``500`` / ``503`` explicitly previously implied ``/health`` itself
could return them, which is not the case (``/health`` is liveness-only).

Declaring the schema here also forces FastAPI to publish ``ProblemDetails``
as a named component in ``/openapi.json``, which is the F004 contract surface
other features (LIP-E001-F002 etc.) build on.
"""

from typing import Any

from fastapi import APIRouter

from app.schemas import HealthResponse, ProblemDetails

router = APIRouter(tags=["health"])

# ``model=ProblemDetails`` registers the schema in components.schemas so
# downstream codegen tools see a reusable type. ``application/problem+json``
# is added to ``content`` so the spec advertises the *runtime* media type
# (the handler in ``app/api/errors.py`` emits ``application/problem+json``,
# not ``application/json``); FastAPI auto-fills the schema reference for
# every media-type entry from the ``model``.
_PROBLEM_RESPONSE: dict[str, Any] = {
    "model": ProblemDetails,
    "description": "Problem details (RFC 7807)",
    "content": {"application/problem+json": {}},
}


@router.get(
    "/health",
    operation_id="getHealth",
    responses={"default": _PROBLEM_RESPONSE},
)
async def health() -> HealthResponse:
    """Liveness probe. Returns 200 if the process is alive.

    The return type annotation is FastAPI's source of the response model
    (FastAPI 0.100+ infers ``response_model`` from the annotation and the
    explicit kwarg is now redundant — the FAST001 ruff rule enforces
    this).
    """
    return HealthResponse()
