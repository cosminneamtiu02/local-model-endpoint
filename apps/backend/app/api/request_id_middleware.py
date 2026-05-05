"""Request middleware — request ID propagation + per-request access log.

Implemented as pure ASGI middleware (not BaseHTTPMiddleware) to avoid the
cancellation and contextvar-fork issues documented in encode/starlette
#1438 and #1715 — cancellation must propagate cleanly so a disconnected
consumer releases the in-flight semaphore slot.

Two concerns layered on the ASGI scope:
1. Validate / mint `X-Request-ID` and bind it via structlog contextvars
   so every log line in the request carries it.
2. Emit a single `request_completed` log line per request with duration
   / status / method / path. This replaces uvicorn's access log
   (silenced in core/logging.py).
"""

import asyncio
import contextlib
import time
import uuid
from http import HTTPStatus
from typing import Final

import structlog
from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import ascii_safe, elapsed_ms
from app.schemas import ProblemDetails
from app.schemas.wire_constants import (
    ABOUT_BLANK_TYPE,
    CONTENT_LANGUAGE,
    PROBLEM_JSON_MEDIA_TYPE,
    UUID_REGEX,
)

# Request paths that are too noisy to log per-request (health checks
# fire on a tight poll loop and would dominate the log volume). The
# request_id binding still happens; only the trailing access line is
# skipped. Add a path here ONLY if (a) its 2xx volume would dominate
# logs in steady state AND (b) degraded (4xx/5xx) responses on that path
# are still operator-actionable (the suppress rule below preserves the
# degraded-response signal). A future ``/readyz`` (LIP-E006-F001) is
# NOT a candidate — operators want every readyz failure visible.
_ACCESS_LOG_SUPPRESSED_PATHS: Final[frozenset[str]] = frozenset({"/health"})

# C0 control characters and DEL — anything in this range injected into
# X-Request-ID would forge log lines under non-JSON renderers.
_C0_CONTROL_UPPER: Final[int] = 0x20
_DEL_CHAR: Final[int] = 0x7F

# Truncation cap on the rejected client-supplied X-Request-ID preview in
# logs. Bounds log-injection blast radius (the ascii-replace + control-char
# checks are the primary defense; truncation is belt-and-suspenders).
_REQUEST_ID_PREVIEW_MAX_CHARS: Final[int] = 32

# Truncation cap on the rejected request path reflected into the 413
# problem+json body's ``instance`` field. Symmetric with
# ``ValidationErrorDetail.field``'s 512-char cap so a pathological consumer
# cannot amplify a single 60K-char-URL POST into a multi-KB error body.
_INSTANCE_PREVIEW_MAX_CHARS: Final[int] = 512

# Sentinel status code emitted in the access log when a request is
# cancelled before the handler reached ``http.response.start``. This is
# the nginx convention "Client Closed Request" — not a real IANA HTTP
# status (the wire response is whatever Starlette emits for the unhandled
# CancelledError; this is access-log telemetry only). Distinguishing
# cancelled-disconnects from genuine 5xx prevents long-poll inference
# disconnects from inflating operator dashboards keyed on
# ``status_code >= 500``.
_CLIENT_CLOSED_REQUEST_STATUS: Final[int] = 499

# Maximum allowed Content-Length on the request body. Larger payloads are
# rejected before Starlette buffers them, defending against accidental retry
# loops or pathological consumers OOM-ing uvicorn on the 16 GB M4 host.
# 64 MiB is well above any realistic single audio clip / multimodal prompt
# and far below memory-pressure territory; not a configurable wire knob.
_MAX_REQUEST_BODY_BYTES: Final[int] = 64 * 1024 * 1024

logger = structlog.get_logger(__name__)


def _resolve_access_log_status(captured_status: int, unhandled_exc: BaseException | None) -> int:
    """Compute the access-log status from raw ASGI signals.

    When the app raises before sending ``http.response.start``, ``captured_status``
    stays at 0 — Starlette's outer ``ServerErrorMiddleware`` will translate the
    exception to a 500 on the wire. We surface that as 500 in the access log
    so log filters keyed on ``status_code >= 500`` actually find these requests.

    ``CancelledError`` is special-cased to ``499`` (the nginx "Client Closed
    Request" sentinel): a consumer disconnect mid-inference is a routine event
    in LIP's domain (long-poll chats from up to 4 LAN consumers), not a server
    bug. Logging those at ``status=500`` would inflate the 5xx rate metric
    operators page on, masking real handler crashes.
    """
    if captured_status != 0 or unhandled_exc is None:
        return captured_status
    if isinstance(unhandled_exc, asyncio.CancelledError):
        return _CLIENT_CLOSED_REQUEST_STATUS
    return int(HTTPStatus.INTERNAL_SERVER_ERROR)


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
        # Control-flow conversion: a malformed Content-Length header (non-int)
        # encodes "we don't know the length" — surface as None so the size
        # guard treats the request as length-unknown (allowed; chunked
        # uploads are also length-unknown). Not a "silent swallow" per
        # CLAUDE.md; the parse failure encodes a known business case.
        return None


async def _send_413_problem_json(send: Send, request_id: str, path: str) -> None:
    """Send a minimal RFC 7807 problem+json 413 response.

    Bypasses the exception handler chain (which lives below this middleware
    in the ASGI stack); the handler chain owns the typed-DomainError shape,
    so this wire body is built by going through the same :class:`ProblemDetails`
    schema to keep the wire shape in sync (no hand-rolled JSON literal that
    could drift from the canonical schema).

    ``code="REQUEST_TOO_LARGE"`` is a string literal — there is no
    DomainError class for it because the middleware sits above the handler
    chain and cannot raise typed exceptions. ProblemDetails' ``code`` field
    is regex-validated (SCREAMING_SNAKE), not class-bound, so the literal
    satisfies the wire contract.

    ``path`` is truncated symmetric with ``ValidationErrorDetail.field``'s
    512-char cap so a pathological consumer cannot amplify a single
    long-URL POST into a multi-KB error body.
    """
    bounded_path = path[:_INSTANCE_PREVIEW_MAX_CHARS]
    problem = ProblemDetails(
        type=ABOUT_BLANK_TYPE,
        title="Payload Too Large",
        status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        code="REQUEST_TOO_LARGE",
        detail=f"Request body exceeds the {_MAX_REQUEST_BODY_BYTES}-byte limit.",
        request_id=request_id,
        instance=bounded_path,
    )
    # No ``exclude_none=False`` — that's the Pydantic v2 default; passing it
    # explicitly drifts from the bare ``model_dump_json()`` shape used at
    # ``exception_handlers._problem_response``. The 413 path has no
    # ProblemExtras / typed-params spread that would need ``None`` preservation.
    body = problem.model_dump_json().encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            "headers": [
                (b"content-type", PROBLEM_JSON_MEDIA_TYPE.encode("ascii")),
                (b"content-language", CONTENT_LANGUAGE.encode("ascii")),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"x-request-id", request_id.encode("ascii")),
            ],
        },
    )
    await send({"type": "http.response.body", "body": body})


class RequestIdMiddleware:
    """Pure ASGI middleware that attaches a request ID + access log to every request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:  # noqa: PLR0915 — single-pass ASGI hot path: header validation, contextvar binding, body-size guard, send-wrapper, finally-block access log; splitting would require shared mutable state.
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
        # ``ascii_safe`` decodes with byte-level replacement and ASCII-cleans
        # the result so any byte outside printable ASCII (CRLF, NUL,
        # extended-latin) becomes ``?`` — neutralizes log-injection vectors
        # that ConsoleRenderer would otherwise emit raw. ``max_chars`` is
        # left at the default; the regex match below caps the practical
        # length to ``REQUEST_ID_LENGTH`` regardless.
        client_id = ascii_safe(client_id_raw)
        # Walrus memoizes ``ord(c)`` across the two-arm comparison so the per-
        # char hot path on every request resolves with one ``ord()`` call.
        if any((o := ord(c)) < _C0_CONTROL_UPPER or o == _DEL_CHAR for c in client_id):
            client_id = "<non-printable>"
        match_result = UUID_REGEX.match(client_id) if client_id else None

        # Resolve method/path early so the rejected-id warning below can
        # carry the routing context (operators need to know which endpoint
        # the malformed ID targeted; flagging only by request-id preview is
        # not enough to attribute a flood of bad IDs to a culprit consumer).
        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))

        # Resolve client IP/port from the ASGI scope once. Bound to
        # contextvars below so EVERY per-request log line — including
        # exception handlers' ``*_raised`` events and the catch-all
        # ``internal_error_5xx_raised`` — carries the originating client
        # without joining by request_id. For a 4-consumer LAN service,
        # knowing which consumer originated a 500 is the difference between
        # "page that team's owner" and "page everyone."
        client_ip, client_port = scope.get("client") or (None, None)

        rejected_client_id = bool(client_id) and match_result is None
        if match_result is not None:
            preview = ""
            request_id = client_id
            request_id_source = "client"
        else:
            preview = client_id[:_REQUEST_ID_PREVIEW_MAX_CHARS] if rejected_client_id else ""
            request_id = str(uuid.uuid4())
            request_id_source = "generated"

        # Bind request_id + method + path + request_id_source BEFORE any
        # pre-yield log lines so ``request_id_rejected_client_value`` /
        # ``request_body_too_large`` / ``request_completed`` all pick up
        # the routing contextvars via ``merge_contextvars`` without each
        # call site re-passing them. Binding ``request_id_source`` here
        # (rather than only on the rejected-id warning) makes a jq filter
        # ``select(.request_id_source == "client")`` find every per-request
        # log line on the happy client-supplied path — symmetric with the
        # ``request_id_source="fallback"`` bind in
        # ``exception_handlers._resolve_request_id``. ``phase="request"``
        # mirrors the lifespan binding (``phase="lifespan"`` in
        # router_registry.lifespan_resources) so a jq filter
        # ``select(.phase == "request")`` greps every per-request log line.
        # Cleanup is guaranteed by the ``clear_contextvars()`` call at the
        # start of the next request entry.
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=method,
            path=path,
            phase="request",
            request_id_source=request_id_source,
            client_ip=client_ip,
            client_port=client_port,
        )

        if rejected_client_id:
            # rejected_reason / rejected_byte_total give triage-actionable
            # signal beyond the bare preview when a control-char rewrite
            # collapsed the value to "<non-printable>". ``request_id_source``
            # flows in via ``merge_contextvars`` from the bind above (no
            # need to pass it again at the call site). ``had_rejected_client_id``
            # is also bound on contextvars so the trailing ``request_completed``
            # line carries it — operators can grep ``select(.event ==
            # "request_completed" and .had_rejected_client_id == true)`` for
            # "consumer with bad header that we re-stamped" without
            # self-joining the warning + completed log streams.
            had_control_chars = client_id == "<non-printable>"
            structlog.contextvars.bind_contextvars(had_rejected_client_id=True)
            logger.warning(
                "request_id_rejected_client_value",
                supplied_value_preview=preview,
                rejected_reason=("control_char" if had_control_chars else "format_mismatch"),
                rejected_byte_total=len(client_id_raw),
            )

        # Park on scope["state"] so request.state.request_id reads it
        # via Starlette's State accessor inside route handlers and the
        # exception-handler chain.
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        captured_status: int = 0
        start = time.perf_counter()
        request_id_header = (b"x-request-id", request_id.encode("ascii"))

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
            # Body-size DoS guard runs INSIDE the try so the trailing
            # ``request_completed`` line in the finally block fires for
            # 413s too — operators dashboarding on per-request rate /
            # status_code distribution would otherwise silently undercount
            # the 413 surface. Content-Length is the primary signal
            # (always set by HTTP/1.1 fixed-size requests); chunked
            # uploads without a length header are not a current LIP
            # profile (LAN-local backend clients send fixed-size JSON),
            # so absence is permitted.
            content_length = _content_length_from_scope(scope)
            if content_length is not None and content_length > _MAX_REQUEST_BODY_BYTES:
                logger.warning(
                    "request_body_too_large",
                    content_length=content_length,
                    limit=_MAX_REQUEST_BODY_BYTES,
                )
                await _send_413_problem_json(send, request_id, path)
                # Stamp the captured status manually since the 413 path
                # bypasses ``send_with_request_id`` (it wraps neither the
                # response.start nor calls into ``self.app``).
                captured_status = int(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            await self.app(scope, receive, send_with_request_id)
        except BaseException as exc:
            # Capture and re-raise so Starlette's outer ServerErrorMiddleware
            # still serializes the response, but the access-log line below
            # gets the real status (500) instead of the 0 sentinel that
            # would silently fall outside operator log filters.
            unhandled_exc = exc
            raise
        finally:
            effective_status = _resolve_access_log_status(captured_status, unhandled_exc)
            # Health-check pings are silenced unless degraded — a 4xx/5xx
            # /health response is the case operators DO want to see. The OK..<400
            # window matches the 2xx/3xx happy-path family per RFC 9110 §15.
            should_suppress_access_log = (
                path in _ACCESS_LOG_SUPPRESSED_PATHS
                and HTTPStatus.OK <= effective_status < HTTPStatus.BAD_REQUEST
            )
            if not should_suppress_access_log:
                duration_ms = elapsed_ms(start)
                # ``client_ip`` / ``client_port`` / ``method`` / ``path`` /
                # ``request_id_source`` / ``error_code`` (set by exception
                # handlers) flow in via ``merge_contextvars`` from the bind
                # above. ``request_id_source``, ``had_rejected_client_id``,
                # and ``error_code`` ARE re-read off contextvars and passed
                # as explicit kwargs as defense-in-depth — same pattern the
                # unhandled-exception handler uses for ``method``/``path``
                # in ``exception_handlers``. A future refactor narrowing
                # the contextvar lifetime won't drop these from the access
                # log mid-flight. ``error_code`` is bound by typed exception
                # handlers when an error fires; absent on the happy path.
                bound = structlog.contextvars.get_contextvars()
                error_code = bound.get("error_code")
                # Wrap the access-log emit in suppress(Exception) so a
                # rendering failure (e.g. a future contextvar with a
                # non-JSON-serializable value tripping JSONRenderer) cannot
                # mask the body's real BaseException via finally-raises-finally:
                # Python re-raises the finally exception and drops the
                # original. The access log is best-effort telemetry; losing
                # one line is preferable to losing a 5xx traceback.
                with contextlib.suppress(Exception):
                    logger.info(
                        "request_completed",
                        status_code=effective_status,
                        duration_ms=duration_ms,
                        request_id_source=request_id_source,
                        had_rejected_client_id=rejected_client_id,
                        error_code=error_code,
                    )


def configure_middleware(application: FastAPI) -> None:
    """Attach middleware to the FastAPI app.

    Parameter named ``application`` for symmetry with ``register_routers``
    and ``register_exception_handlers`` — three sibling helpers with one
    parameter convention so the call site in ``app.main.create_app`` reads
    uniformly.

    No CORS, no trusted-hosts, no auth — local-network-only service per
    docs/disambiguated-idea.md (Security boundary). Add CORS scaffolding
    only when a non-server-to-server consumer (e.g., browser dev tool)
    needs it.

    ``add_middleware`` appends in LIFO order — the LAST added is the
    OUTERMOST wrapper. ``RequestIdMiddleware`` must stay last-added so
    it stays outermost; that's what guarantees ``request_id`` is bound
    BEFORE any nested middleware (compression, etc.) emits log lines.
    A future second middleware (e.g. body-compression) MUST be added
    BEFORE this line so it lands inside RequestIdMiddleware's wrapper.
    """
    application.add_middleware(RequestIdMiddleware)
