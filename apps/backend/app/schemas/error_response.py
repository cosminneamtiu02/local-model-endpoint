"""Top-level error response schema for OpenAPI documentation.

ErrorResponse is wired into route decorators via `responses={...}` once the LIP
feature router lands (LIP-E001-F002). Until then it serves as the canonical
error envelope reference for tests and contract specs. The exception handler in
api/errors.py builds error responses directly as JSONResponse dicts at runtime.
ErrorResponse is never instantiated in application code.
"""

from pydantic import BaseModel

from app.schemas.error_body import ErrorBody


class ErrorResponse(BaseModel):
    """Top-level error response shape."""

    error: ErrorBody
