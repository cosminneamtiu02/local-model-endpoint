"""Health endpoint — liveness probe mounted at root, outside /v1/."""

from typing import Any, Final

from fastapi import APIRouter, status

from app.schemas import HealthResponse, ProblemDetails

router = APIRouter(tags=["health"])

# OpenAPI default-response for every error path; content key advertises
# the application/problem+json media type the error handler emits.
# ``/health`` itself never raises a DomainError (no deps, no validation,
# no IO), but this declaration is the project-wide publishing point for
# the ``ProblemDetails`` component in the OpenAPI components map — the
# contract suite asserts on it. Future feature routers that have typed-
# error surfaces declare per-route 4xx/5xx entries; this default-only
# entry remains for /health as the global error-shape advertisement.
_PROBLEM_RESPONSE: Final[dict[str, Any]] = {
    "model": ProblemDetails,
    "description": "Problem details (RFC 7807)",
    "content": {"application/problem+json": {}},
}

# Explicit 200 entry so the OpenAPI spec advertises both the success
# response (``application/json`` with HealthResponse) AND the default
# error path symmetrically. FastAPI infers 200 from the return-type
# annotation, but the inferred entry is content-typeless; declaring it
# here makes the wire contract self-documenting in /openapi.json.
_HEALTH_OK_RESPONSE: Final[dict[str, Any]] = {
    "model": HealthResponse,
    "description": "Liveness probe — process is alive",
    "content": {"application/json": {}},
}


@router.get(
    "/health",
    operation_id="getHealth",
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_200_OK: _HEALTH_OK_RESPONSE,
        "default": _PROBLEM_RESPONSE,
    },
)
async def get_health() -> HealthResponse:
    """Liveness probe. Returns 200 if the process is alive.

    Verb-form name (``get_health``) per CLAUDE.md "Python functions:
    snake_case verbs". The OpenAPI ``operation_id="getHealth"`` is the
    consumer-facing handle; matching the Python function name to it
    keeps the convention legible.

    The return type annotation is FastAPI's source of the response model
    (FastAPI 0.100+ infers ``response_model`` from the annotation and the
    explicit kwarg is now redundant — the FAST001 ruff rule enforces
    this).

    The route is silent on the 2xx happy path (RequestIdMiddleware
    suppresses ``request_completed`` for /health 2xx/3xx) and only the
    middleware logs on degraded responses; no body-side log line is
    needed today.
    """
    return HealthResponse()
