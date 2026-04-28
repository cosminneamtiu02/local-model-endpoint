"""Top-level error response schema for OpenAPI documentation.

ErrorResponse is the canonical error envelope. The exception handler in
api/errors.py constructs it via `ErrorResponse(error=ErrorBody(...))`
and returns `model_dump()` to FastAPI's JSONResponse, so the wire shape
stays in lockstep with the schema. ErrorResponse is also wired into
route decorators via `responses={...}` once the LIP feature router
lands (LIP-E001-F002).
"""

from pydantic import BaseModel, ConfigDict

from app.schemas.error_body import ErrorBody


class ErrorResponse(BaseModel):
    """Top-level error response shape."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorBody
