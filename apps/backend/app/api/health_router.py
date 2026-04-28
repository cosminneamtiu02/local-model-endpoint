"""Health endpoint — liveness probe mounted at root, outside /v1/."""

from typing import Any

from fastapi import APIRouter, status

from app.schemas import HealthResponse, ProblemDetails

router = APIRouter(tags=["health"])

# OpenAPI default-response for every error path; content key advertises
# the application/problem+json media type the error handler emits.
_PROBLEM_RESPONSE: dict[str, Any] = {
    "model": ProblemDetails,
    "description": "Problem details (RFC 7807)",
    "content": {"application/problem+json": {}},
}


@router.get(
    "/health",
    operation_id="getHealth",
    status_code=status.HTTP_200_OK,
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
