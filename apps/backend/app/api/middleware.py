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

import json
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

# Status family bounds for the access-log suppression check on /health.
_HTTP_STATUS_OK_FLOOR: Final[int] = 200
_HTTP_STATUS_REDIRECT_CEILING: Final[int] = 400

# When the app raises before sending http.response.start, captured_status
# stays 0 — Starlette's outer ServerErrorMiddleware will translate the
# exception to a 500 on the wire. Surface that as 500 in the access log so
# log filters keyed on `status_code >= 500` actually find these requests.
_STATUS_ON_UNCAUGHT_EXCEPTION: Final[int] = 500

# Truncation cap on the rejected client-supplied X-Request-ID preview in
# logs. Bounds log-injection blast radius (the ascii-replace + control-char
# checks are the primary defense; truncation is belt-and-suspenders).
_REQUEST_ID_PREVIEW_MAX_CHARS: Final[int] = 32

# Maximum allowed Content-Length on the request body. Larger payloads are
# rejected before Starlette buffers them, defending against accidental retry
# loops or pathological consumers OOM-ing uvicorn on the 16 GB M4 host.
# 64 MiB is well above any realistic single audio clip / multimodal prompt
# and far below memory-pressure territory; not a configurable wire knob.
_MAX_REQUEST_BODY_BYTES: Final[int] = 64 * 1024 * 1024
_PROBLEM_JSON_MEDIA_TYPE: Final[bytes] = b"application/problem+json; charset=utf-8"
_CONTENT_LANGUAGE: Final[bytes] = b"en"
_REQUEST_ENTITY_TOO_LARGE: Final[int] = 413

logger = structlog.get_logger(__name__)


def _content_length_from_scope(scope: Scope) -> int | None:
    """Read Content-Length from ASGI scope headers; None if absent or unparseable."""
    raw = next(
        (v for k, v in scope.get("headers", []) if k == b"content-length"),
        None,
    )
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


async def _send_413_problem_json(send: Send, request_id: str, path: str) -> None:
    """Send a minimal RFC 7807 problem+json 413 response without invoking the
    exception handler chain (which lives below this middleware in the ASGI
    stack). The handler chain owns the typed-DomainError shape; this wire
    body is built by hand to keep the middleware self-contained.
    """
    body = json.dumps(
        {
            "type": "about:blank",
            "title": "Payload Too Large",
            "status": _REQUEST_ENTITY_TOO_LARGE,
            "detail": (f"Request body exceeds the {_MAX_REQUEST_BODY_BYTES}-byte limit."),
            "instance": path,
            "code": "REQUEST_TOO_LARGE",
            "request_id": request_id,
        },
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": _REQUEST_ENTITY_TOO_LARGE,
            "headers": [
                (b"content-type", _PROBLEM_JSON_MEDIA_TYPE),
                (b"content-language", _CONTENT_LANGUAGE),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"x-request-id", request_id.encode("latin-1")),
            ],
        },
    )
    await send({"type": "http.response.body", "body": body})


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
        # Walrus memoizes ``ord(c)`` across the two-arm comparison so the per-
        # char hot path on every request resolves with one ``ord()`` call.
        if any((o := ord(c)) < _C0_CONTROL_UPPER or o == _DEL_CHAR for c in client_id):
            client_id = "<non-printable>"
        match_result = _UUID_PATTERN.match(client_id) if client_id else None

        if client_id and match_result is None:
            preview = client_id[:_REQUEST_ID_PREVIEW_MAX_CHARS]
            request_id = str(uuid.uuid4())
            # rejected_reason / rejected_byte_total give triage-actionable
            # signal beyond the bare preview when a control-char rewrite
            # collapsed the value to "<non-printable>".
            had_control_chars = client_id == "<non-printable>"
            logger.warning(
                "request_id_rejected_client_value",
                supplied_value_preview=preview,
                rejected_reason=("control_char" if had_control_chars else "format_mismatch"),
                rejected_byte_total=len(client_id_raw),
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

        # Body-size DoS guard: reject early before Starlette buffers the
        # whole body into memory. Content-Length is the primary signal
        # (always set by HTTP/1.1 fixed-size requests); chunked uploads
        # without a length header are not a current LIP profile (LAN-local
        # backend clients send fixed-size JSON), so the absence of
        # Content-Length is permitted.
        content_length = _content_length_from_scope(scope)
        if content_length is not None and content_length > _MAX_REQUEST_BODY_BYTES:
            logger.warning(
                "request_body_too_large",
                request_id=request_id,
                method=method,
                path=path,
                content_length=content_length,
                limit=_MAX_REQUEST_BODY_BYTES,
            )
            await _send_413_problem_json(send, request_id, path)
            return

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
            request_id_header = (b"x-request-id", request_id.encode("latin-1"))

            async def send_with_request_id(message: Message) -> None:
                nonlocal captured_status
                if message["type"] == "http.response.start":
                    captured_status = int(message.get("status", 0))
                    # Unpack the existing headers iterable into a fresh list
                    # with the request-id tuple appended; one allocation, no
                    # imperative ``append`` step on the hot per-response path.
                    message = {
                        **message,
                        "headers": [*message.get("headers", []), request_id_header],
                    }
                await send(message)

            unhandled_exc: BaseException | None = None
            try:
                await self.app(scope, receive, send_with_request_id)
            except BaseException as exc:
                # Capture and re-raise so Starlette's outer ServerErrorMiddleware
                # still serializes the response, but the access-log line below
                # gets the real status (500) instead of the 0 sentinel that
                # would silently fall outside operator log filters.
                unhandled_exc = exc
                raise
            finally:
                effective_status = (
                    _STATUS_ON_UNCAUGHT_EXCEPTION
                    if captured_status == 0 and unhandled_exc is not None
                    else captured_status
                )
                # Health-check pings are silenced unless degraded — a 4xx/5xx
                # /health response is the case operators DO want to see.
                suppress = (
                    path in _ACCESS_LOG_SUPPRESSED_PATHS
                    and _HTTP_STATUS_OK_FLOOR <= effective_status < _HTTP_STATUS_REDIRECT_CEILING
                )
                if not suppress:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    client = scope.get("client")
                    # Explicit method=/path= kwargs are belt-and-suspenders
                    # alongside merge_contextvars: a future regression that
                    # drops the contextvar processor would otherwise silently
                    # strip routing context from the access log.
                    # client_host is the LAN-trusted consumer's peer IP — fine
                    # to log unconditionally for this single-developer LAN
                    # profile (consumers are self-owned). Revisit (toggle or
                    # redact) the day a non-self-owned client class appears.
                    logger.info(
                        "request_completed",
                        method=method,
                        path=path,
                        status_code=effective_status,
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
