"""Exception handlers — maps DomainError subclasses to HTTP error responses."""

from typing import Final

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions import DomainError, InternalError, ValidationFailedError
from app.schemas.error_body import ErrorBody
from app.schemas.error_detail import ErrorDetail
from app.schemas.error_response import ErrorResponse

_UNKNOWN_REQUEST_ID: Final[str] = "unknown"

logger = structlog.get_logger(__name__)


def _get_request_id(request: Request) -> str:
    """Extract request ID from request state, set by RequestIdMiddleware."""
    request_id = getattr(request.state, "request_id", _UNKNOWN_REQUEST_ID)
    return request_id if isinstance(request_id, str) else _UNKNOWN_REQUEST_ID


def _build_error_response(
    *,
    status_code: int,
    code: str,
    params: dict[str, str | int | float | bool],
    details: list[ErrorDetail] | None,
    request_id: str,
) -> JSONResponse:
    """Construct the canonical error envelope and serialize it to JSON.

    Centralizes ErrorBody/ErrorResponse construction so the wire shape
    stays in lockstep with the Pydantic schemas — adding a field to
    ErrorBody automatically propagates without touching every handler.
    """
    body = ErrorBody(code=code, params=params, details=details, request_id=request_id)
    envelope = ErrorResponse(error=body)
    return JSONResponse(status_code=status_code, content=envelope.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""

    @app.exception_handler(DomainError)
    async def handle_domain_error(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
        request: Request,
        exc: DomainError,
    ) -> JSONResponse:
        return _build_error_response(
            status_code=exc.http_status,
            code=exc.code,
            params=exc.params.model_dump() if exc.params else {},
            details=None,
            request_id=_get_request_id(request),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = exc.errors()
        details = [
            ErrorDetail(
                field=" -> ".join(str(loc) for loc in e.get("loc", [])),
                reason=str(e.get("msg", "Unknown validation error")),
            )
            for e in errors
        ]
        first = details[0] if details else ErrorDetail(field="unknown", reason="unknown")
        return _build_error_response(
            status_code=ValidationFailedError.http_status,
            code=ValidationFailedError.code,
            params={"field": first.field, "reason": first.reason},
            details=details,
            request_id=_get_request_id(request),
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
        return _build_error_response(
            status_code=InternalError.http_status,
            code=InternalError.code,
            params={},
            details=None,
            request_id=request_id,
        )
