"""Exception handlers — map errors to RFC 7807 ``application/problem+json``.

The handler chain is:
    DomainError                → typed RFC 7807 body with the error's typed
                                 params spread at root.
    RequestValidationError     → ``VALIDATION_FAILED`` with a
                                 ``validation_errors`` extension array.
    Exception                  → ``INTERNAL_ERROR`` with no params and a
                                 generic detail (no PII / stack-trace leak).

Body shape (every handler):
    {
      "type":       "urn:lip:error:<code-kebab>",
      "title":      "<short summary>",
      "status":     <int>,
      "detail":     "<per-instance message>",
      "instance":   "<request URL path>",
      "code":       "<SCREAMING_SNAKE>",
      "request_id": "<uuid>",
      ...spread per-error params (or validation_errors for 422)
    }
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions import DomainError, InternalError, ValidationFailedError
from app.schemas import ProblemDetails

logger = structlog.get_logger(__name__)

PROBLEM_JSON_MEDIA_TYPE = "application/problem+json"


def _get_request_id(request: Request) -> str:
    """Extract request ID from request state, set by RequestIdMiddleware."""
    return getattr(request.state, "request_id", "unknown")


def _build_body(
    exc: DomainError,
    request: Request,
    *,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the RFC 7807 body for a DomainError.

    Per-error typed params (``exc.params``) are spread at root level per RFC
    7807's extension convention. ``extras`` carries the additional extension
    fields (e.g. ``validation_errors`` for 422) and is merged last.
    """
    spread: dict[str, Any] = exc.params.model_dump() if exc.params else {}
    problem = ProblemDetails(
        type=exc.type_uri,
        title=exc.title,
        status=exc.http_status,
        detail=exc.detail(),
        instance=request.url.path,
        code=exc.code,
        request_id=_get_request_id(request),
        **spread,
        **(extras or {}),
    )
    return problem.model_dump()


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""

    @app.exception_handler(DomainError)
    async def handle_domain_error(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
        request: Request,
        exc: DomainError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=_build_body(exc, request),
            media_type=PROBLEM_JSON_MEDIA_TYPE,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        # Project Pydantic's per-error tuple loc into a dotted-path string. We
        # preserve Pydantic's natural iteration order — alphabetizing would
        # decouple validation_errors from the order the consumer's request
        # listed them, which is the more useful debugging signal.
        validation_errors: list[dict[str, str]] = [
            {
                "field": ".".join(str(loc) for loc in e.get("loc", [])),
                "reason": str(e.get("msg", "Unknown validation error")),
            }
            for e in exc.errors()
        ]
        first = (
            validation_errors[0] if validation_errors else {"field": "unknown", "reason": "unknown"}
        )
        domain_err = ValidationFailedError(field=first["field"], reason=first["reason"])
        return JSONResponse(
            status_code=domain_err.http_status,
            content=_build_body(
                domain_err,
                request,
                extras={"validation_errors": validation_errors},
            ),
            media_type=PROBLEM_JSON_MEDIA_TYPE,
        )

    @app.exception_handler(Exception)
    async def handle_unhandled(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        request_id = _get_request_id(request)
        logger.exception(
            "unhandled_exception",
            request_id=request_id,
            exc_type=type(exc).__name__,
        )
        domain_err = InternalError()
        return JSONResponse(
            status_code=domain_err.http_status,
            content=_build_body(domain_err, request),
            media_type=PROBLEM_JSON_MEDIA_TYPE,
        )
