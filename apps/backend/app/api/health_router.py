"""Health endpoint — mounted at root, outside /api/v1/.

Liveness only in v1. Readiness will be added by LIP-E006-F001 when the
warm-up signal from LIP-E005-F001 is wired during feature-dev.

The ``responses=`` argument documents that ANY route in this app — including
``/health`` itself — produces ``ProblemDetails`` (RFC 7807 ``application/
problem+json``) for non-2xx outcomes. This is the truthful documentation:
the global exception handler in ``app/api/errors.py`` runs against every
route. Declaring the schema here also forces FastAPI to publish
``ProblemDetails`` as a named component in ``/openapi.json``, which is the
F004 contract surface other features (LIP-E001-F002 etc.) build on.
"""

from fastapi import APIRouter

from app.schemas import ProblemDetails

router = APIRouter(tags=["health"])

_PROBLEM_RESPONSE = {"model": ProblemDetails, "description": "Problem details (RFC 7807)"}


@router.get(
    "/health",
    responses={
        500: _PROBLEM_RESPONSE,
        503: _PROBLEM_RESPONSE,
    },
)
async def health() -> dict[str, str]:
    """Liveness probe. Returns 200 if the process is alive."""
    return {"status": "ok"}
