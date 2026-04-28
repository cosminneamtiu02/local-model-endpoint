"""Request middleware — request ID propagation + per-request access log.

Implemented as pure ASGI middleware (not BaseHTTPMiddleware) to avoid the
cancellation and contextvar-fork issues documented in encode/starlette
#1438 and #1715 — cancellation must propagate cleanly so a disconnected
consumer releases the in-flight semaphore slot.

Two concerns layered on the ASGI scope:
1. Validate / mint `X-Request-Id` and bind it via structlog contextvars
   so every log line in the request carries it.
2. Emit a single `request_completed` log line per request with duration
   / status / method / path. This replaces uvicorn's access log
   (silenced in core/logging.py).
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

# C0 control characters and DEL — anything in this range injected into
# X-Request-ID would forge log lines under non-JSON renderers.
_C0_CONTROL_UPPER: Final[int] = 0x20
_DEL_CHAR: Final[int] = 0x7F

logger = structlog.get_logger(__name__)


class RequestIdMiddleware:
    """Pure ASGI middleware that attaches a request ID + access log to every request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Clear contextvars at the request boundary so any prior request's
        # ad-hoc binds (error_code from exception handlers, fallback request_id)
        # do not leak into this request's log lines.
        structlog.contextvars.clear_contextvars()

        # Accept client-provided request ID only if it's a valid UUID;
        # otherwise generate a new one. Prevents log injection. Walk the
        # ASGI headers iterable directly — they are an iterable of
        # (bytes, bytes) tuples; building a full dict to fetch one key
        # is per-request waste on the hot path.
        client_id_raw = next(
            (v for k, v in scope.get("headers", []) if k == b"x-request-id"),
            b"",
        )
        # ASCII-only decode with replacement: any byte outside printable
        # ASCII (CRLF, NUL, extended-latin) becomes �, neutralising
        # log-injection vectors that ConsoleRenderer would otherwise emit
        # raw.
        client_id = client_id_raw.decode("ascii", errors="replace")
        if any(ord(c) < _C0_CONTROL_UPPER or ord(c) == _DEL_CHAR for c in client_id):
            client_id = "<non-printable>"
        match_result = _UUID_PATTERN.match(client_id) if client_id else None

        if client_id and match_result is None:
            # Truncate before logging to bound log-injection blast radius
            # (the ascii-replace + control-char check above is the primary
            # defense; truncation is belt-and-suspenders).
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
