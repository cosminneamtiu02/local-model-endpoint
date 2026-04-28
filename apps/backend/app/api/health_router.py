"""Health endpoint — mounted at root, outside /api/v1/.

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

from fastapi import APIRouter

from app.schemas import ProblemDetails

router = APIRouter(tags=["health"])

_PROBLEM_RESPONSE = {"model": ProblemDetails, "description": "Problem details (RFC 7807)"}


@router.get(
    "/health",
    responses={"default": _PROBLEM_RESPONSE},
)
async def health() -> dict[str, str]:
    """Liveness probe. Returns 200 if the process is alive."""
    return {"status": "ok"}
