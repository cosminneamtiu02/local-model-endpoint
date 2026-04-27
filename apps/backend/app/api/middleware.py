"""Request middleware — request ID propagation only.

Access-log emission, security headers, and CORS were stripped during
project-bootstrap because the service is local-network-only and v1's
Project Boundary defers structured logging emission and browser-
protective surfaces to a future milestone (G3 architectural foundation).
"""

import re
import uuid

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = structlog.get_logger(__name__)

# Valid UUID pattern for X-Request-ID header
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request ID to every request and response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Accept client-provided request ID only if it's a valid UUID.
        # Otherwise generate a new one. Prevents log injection.
        client_id = request.headers.get("X-Request-ID", "")
        request_id = client_id if _UUID_PATTERN.match(client_id) else str(uuid.uuid4())
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def configure_middleware(app: FastAPI) -> None:
    """Attach middleware to the FastAPI app.

    LIP runs only the RequestIdMiddleware in v1.
    """
    app.add_middleware(RequestIdMiddleware)
