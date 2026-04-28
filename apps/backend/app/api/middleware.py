"""Request middleware — request ID propagation + per-request access log.

Implemented as pure ASGI middleware (not BaseHTTPMiddleware) to avoid
the documented cancellation and contextvar-fork issues with
Starlette's BaseHTTPMiddleware (encode/starlette#1438, #1715). With
LIP-E004-F003's per-request timeout, cancellation propagation is
load-bearing: if a consumer disconnects mid-inference, the in-flight
httpx request must be aborted so the semaphore slot frees.

Two concerns layered on the ASGI scope:
1. Validate / mint `X-Request-Id` and bind it via structlog
   contextvars so every log line in the request carries it.
2. Emit a single `request_completed` log line per request with
   duration / status / method / path. This is the structlog-native
   replacement for uvicorn's access log (silenced in core/logging.py).

CORS, security headers, and auth were stripped during project-bootstrap
because the service is local-network-only and v1's Project Boundary
defers browser-protective surfaces to a future milestone.
"""

import re
import time
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

# Request paths that are too noisy to log per-request (health checks
# fire on a tight poll loop and would dominate the log volume). The
# request_id binding still happens; only the trailing access line is
# skipped.
_ACCESS_LOG_SUPPRESSED_PATHS: Final[frozenset[str]] = frozenset({"/health"})

logger = structlog.get_logger(__name__)


class RequestIdMiddleware:
    """Pure ASGI middleware that attaches a request ID + access log to every request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Accept client-provided request ID only if it's a valid UUID;
        # otherwise generate a new one. Prevents log injection. Walk the
        # ASGI headers iterable directly — they are an iterable of
        # (bytes, bytes) tuples; building a full dict to fetch one key
        # is per-request waste on the hot path.
        client_id_raw = next(
            (v for k, v in scope.get("headers", []) if k == b"x-request-id"),
            b"",
        )
        client_id = client_id_raw.decode("latin-1", errors="ignore")
        match_result = _UUID_PATTERN.match(client_id) if client_id else None

        if client_id and match_result is None:
            # A consumer sending a non-UUID X-Request-ID is a client-side
            # configuration bug — recoverable but worth surfacing as a
            # warning so it is visible in any "show me warnings" filter.
            # Truncate the supplied value to bound the log-injection
            # blast radius.
            preview = client_id[:32]
            request_id = str(uuid.uuid4())
            logger.warning(
                "request_id_rejected_client_value",
                supplied_value_preview=preview,
                generated_request_id=request_id,
            )
        elif match_result is not None:
            request_id = client_id
        else:
            request_id = str(uuid.uuid4())

        # Park on scope["state"] so request.state.request_id reads it
        # via Starlette's State accessor inside route handlers and the
        # exception-handler chain.
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        # `nonlocal` is the canonical construct for binding an int from
        # the inner closure — using a 1-element list to fake mutability
        # is an idiomatic anti-pattern (PEP 3104 added nonlocal precisely
        # to avoid that workaround).
        captured_status: int = 0
        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        start = time.perf_counter()

        # Bind request_id + method + path so every log line emitted within
        # the request scope (handlers, services, repositories) carries the
        # routing context. ``merge_contextvars`` injects them on emit;
        # explicit kwargs at call sites would override the contextvar (and
        # would be redundant for these three keys anyway).
        with structlog.contextvars.bound_contextvars(
            request_id=request_id,
            method=method,
            path=path,
        ):

            async def send_with_request_id(message: Message) -> None:
                nonlocal captured_status
                if message["type"] == "http.response.start":
                    captured_status = int(message.get("status", 0))
                    new_headers = list(message.get("headers", []))
                    new_headers.append((b"x-request-id", request_id.encode("latin-1")))
                    message = {**message, "headers": new_headers}
                await send(message)

            try:
                await self.app(scope, receive, send_with_request_id)
            finally:
                # Health-check pings are silenced unless degraded — a 4xx/5xx
                # /health response is the case operators DO want to see.
                suppress = (
                    path in _ACCESS_LOG_SUPPRESSED_PATHS and 200 <= captured_status < 400  # noqa: PLR2004
                )
                if not suppress:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    client = scope.get("client")
                    logger.info(
                        "request_completed",
                        status_code=captured_status,
                        duration_ms=duration_ms,
                        client_host=client[0] if client else None,
                    )


def configure_middleware(app: FastAPI) -> None:
    """Attach middleware to the FastAPI app.

    No CORS, no trusted-hosts, no auth — local-network-only service per
    docs/disambigued-idea.md (Security boundary). Add CORS scaffolding
    only when a non-server-to-server consumer (e.g., browser dev tool)
    needs it.
    """
    app.add_middleware(RequestIdMiddleware)
