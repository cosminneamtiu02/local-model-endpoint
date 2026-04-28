"""Request middleware — request ID propagation only.

Implemented as pure ASGI middleware (not BaseHTTPMiddleware) to avoid
the documented cancellation and contextvar-fork issues with
Starlette's BaseHTTPMiddleware (encode/starlette#1438, #1715). With
LIP-E004-F003's per-request timeout, cancellation propagation is
load-bearing: if a consumer disconnects mid-inference, the in-flight
httpx request must be aborted so the semaphore slot frees.

Access-log emission, security headers, and CORS were stripped during
project-bootstrap because the service is local-network-only and v1's
Project Boundary defers structured logging emission and browser-
protective surfaces to a future milestone (G3 architectural
foundation).
"""

import re
import uuid
from typing import Final

import structlog
from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Valid UUID pattern for X-Request-ID header.
_UUID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

logger = structlog.get_logger(__name__)


class RequestIdMiddleware:
    """Pure ASGI middleware that attaches a request ID to every request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Accept client-provided request ID only if it's a valid UUID;
        # otherwise generate a new one. Prevents log injection.
        headers = dict(scope.get("headers", []))
        client_id = headers.get(b"x-request-id", b"").decode("latin-1", errors="ignore")
        request_id = client_id if _UUID_PATTERN.match(client_id) else str(uuid.uuid4())

        # Park on scope["state"] so request.state.request_id reads it
        # via Starlette's State accessor inside route handlers and the
        # exception-handler chain.
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        with structlog.contextvars.bound_contextvars(request_id=request_id):

            async def send_with_request_id(message: Message) -> None:
                if message["type"] == "http.response.start":
                    new_headers = list(message.get("headers", []))
                    new_headers.append((b"x-request-id", request_id.encode("latin-1")))
                    message = {**message, "headers": new_headers}
                await send(message)

            await self.app(scope, receive, send_with_request_id)


def configure_middleware(app: FastAPI) -> None:
    """Attach middleware to the FastAPI app.

    No CORS, no trusted-hosts, no auth — local-network-only service per
    docs/disambigued-idea.md (Security boundary). Add CORS scaffolding
    only when a non-server-to-server consumer (e.g., browser dev tool)
    needs it.
    """
    app.add_middleware(RequestIdMiddleware)
