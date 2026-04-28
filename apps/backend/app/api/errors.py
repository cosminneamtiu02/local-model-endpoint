"""Exception handlers — map errors to RFC 7807 ``application/problem+json``.

The handler chain (registered, in order, on the FastAPI app):

    DomainError                → typed RFC 7807 body with the error's typed
                                 params spread at root.
    RequestValidationError     → ``VALIDATION_FAILED`` with a
                                 ``validation_errors`` extension array of
                                 ``ValidationErrorDetail`` objects.
    StarletteHTTPException     → un-typed HTTP errors raised by the framework
                                 (404 from missing routes, 405 from method
                                 mismatch, etc.) wrapped into RFC 7807. Per
                                 RFC 7807 §4.2 we use ``type="about:blank"``
                                 for problems with no semantics beyond the
                                 status code.
    Exception                  → ``INTERNAL_ERROR`` with no params and a
                                 generic detail (no PII / stack-trace leak).

Starlette resolves handlers by walking ``type(exc).__mro__`` and selecting
the most specific registered match. Because ``StarletteHTTPException`` is
itself a subclass of ``Exception``, the HTTPException handler must be
registered (not relying on the registration order alone — Starlette is
type-driven, not insertion-order-driven, but registering both keeps intent
explicit and avoids a stray ``HTTPException`` falling through to the
generic ``Exception`` handler).

Body shape (every handler):

    {
      "type":       "urn:lip:error:<code-kebab>" | "about:blank",
      "title":      "<short summary>",
      "status":     <int>,
      "detail":     "<per-instance message>",
      "instance":   "<request URL path>",
      "code":       "<SCREAMING_SNAKE>",
      "request_id": "<uuid>",
      ...spread per-error params (or validation_errors for 422)
    }

Headers on every error response:

    Content-Type:     application/problem+json; charset=utf-8  (RFC 7807 §3)
    Content-Language: en                                       (RFC 7807 §3.1)
    X-Request-ID:     <uuid>                                   (correlation)

The ``Content-Language: en`` header is the v1 contract for "the response is
English-only". When i18n arrives in a future milestone, this value becomes
content-negotiated; the ``title`` and ``detail`` strings (per RFC 7807 §3.1
"SHOULD be localizable") become the i18n hook points.
"""

from __future__ import annotations

import re
import uuid
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Final, cast

import structlog
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.exceptions import DomainError, InternalError, NotFoundError, ValidationFailedError
from app.schemas import ProblemDetails, ProblemExtras, ValidationErrorDetail
from app.schemas.validation_error_detail import FIELD_MAX_CHARS, REASON_MAX_CHARS

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = structlog.get_logger(__name__)

PROBLEM_JSON_MEDIA_TYPE: Final[str] = "application/problem+json; charset=utf-8"
"""RFC 7807 §3 media type, with explicit UTF-8 charset.

RFC 8259 makes UTF-8 implicit for ``application/json``-style payloads, but
declaring it explicitly disambiguates against legacy proxies and intermediary
caches that historically guessed the charset for unknown ``+json`` suffixes.
"""

_CONTENT_LANGUAGE: Final[str] = "en"
"""RFC 7807 §3.1 advertises the language of ``title`` and ``detail``."""

_ABOUT_BLANK: Final[str] = "about:blank"
"""RFC 7807 §4.2 ``type`` value for HTTP errors with no extra semantics."""


_REQUEST_ID_UUID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _resolve_request_id(request: Request) -> tuple[str, bool]:
    """Read the request ID set by :class:`RequestIdMiddleware`.

    Returns ``(request_id, missed_middleware)``. The bool is True only on the
    fallback path so callers can compensate for the missing middleware (e.g.
    explicitly stamp the ``X-Request-ID`` response header that the middleware
    would otherwise have set).

    Returning a fallback UUID instead of a static ``"unknown"`` string keeps
    every emitted ``request_id`` field uniformly UUID-shaped, which matters
    for log-correlation tooling that pattern-matches the format.

    Defense-in-depth: re-validate that ``request.state.request_id`` matches
    the UUID shape even when middleware-stamped — a future handler that writes
    arbitrary strings to ``request.state`` (e.g. an X-Trace-Id pass-through)
    would otherwise leak unvalidated values into every response body's
    ``request_id`` field.
    """
    request_id = getattr(request.state, "request_id", None)
    if (
        isinstance(request_id, str)
        and request_id
        and _REQUEST_ID_UUID_PATTERN.match(request_id) is not None
    ):
        return request_id, False
    fallback = str(uuid.uuid4())
    # Bind request_id + method + path so every subsequent log line for this
    # request carries routing context (the middleware ordinarily binds these;
    # under fallback we duplicate the work so handler-emitted lines don't
    # ship without method/path on the misconfigured-app path).
    structlog.contextvars.bind_contextvars(
        request_id=fallback,
        method=request.method,
        path=request.url.path,
    )
    logger.warning(
        "request_id_missing_in_state",
        fallback_request_id=fallback,
        path=request.url.path,
        method=request.method,
    )
    return fallback, True


def _stamp_request_id_header_if_missed(
    response: Response,
    request_id: str,
    *,
    missed: bool,
) -> None:
    """Set ``X-Request-ID`` on the response only when the middleware did not.

    Avoids duplicating the header (the middleware appends unconditionally on
    its happy path) while still correlating body↔header on the misconfigured-
    app fallback path.
    """
    if missed:
        response.headers["X-Request-ID"] = request_id


def _build_problem_payload(
    exc: DomainError,
    request: Request,
    request_id: str,
    *,
    detail_override: str | None = None,
    extras: ProblemExtras | None = None,
) -> ProblemDetails:
    """Assemble and validate the RFC 7807 :class:`ProblemDetails` for a DomainError.

    Per-error typed params (``exc.params``) are spread at root level per
    RFC 7807's extension-field convention. ``extras`` carries additional
    extension fields (e.g. ``validation_errors`` for 422) and is merged last.

    ``mode="json"`` on the params dump future-proofs against typed params
    that may eventually contain ``datetime`` / ``UUID`` / ``Decimal`` values:
    Pydantic's JSON mode renders them as primitives, whereas the default
    ``mode="python"`` returns native objects that would fail JSON encoding
    downstream.
    """
    spread: dict[str, Any] = exc.params.model_dump(mode="json") if exc.params else {}
    # ProblemDetails uses ``extra='allow'`` at runtime for typed extension
    # fields; pyright cannot prove the TypedDict keys map to ProblemDetails
    # kwargs, so we widen via ``cast`` (keeping the TypedDict as the
    # caller-side contract).
    extras_widened: dict[str, Any] = cast("dict[str, Any]", extras) if extras else {}
    # Defense-in-depth: an extras key colliding with a typed spread key would
    # silently win on the ``**`` merge; raise loud so the bug surfaces at the
    # handler edge rather than as a confusing wire shape.
    collisions = set(spread).intersection(extras_widened)
    if collisions:
        error_message = (
            f"ProblemDetails extras keys collide with typed params: {sorted(collisions)!r}"
        )
        raise RuntimeError(error_message)
    try:
        return ProblemDetails(
            type=exc.type_uri,
            title=exc.title,
            status=exc.http_status,
            detail=detail_override if detail_override is not None else exc.detail(),
            instance=request.url.path,
            code=exc.code,
            request_id=request_id,
            **spread,
            **extras_widened,
        )
    except ValidationError as ve:
        # An exception handler that itself raises bypasses our RFC 7807
        # envelope and ships a bare-text 500. Log-and-fall-back so the
        # consumer always gets problem+json, even on a malformed DomainError
        # (e.g. a future YAML entry with an invalid type_uri).
        logger.exception(
            "problem_details_construction_failed",
            exc_type=type(ve).__name__,
            error_count=len(ve.errors()),
            original_code=exc.code,
        )
        return ProblemDetails(
            type="urn:lip:error:internal-error",
            title="Internal Server Error",
            status=500,
            detail="An unexpected error occurred while building the error response.",
            instance=request.url.path,
            code=InternalError.code,
            request_id=request_id,
        )


def _problem_response(problem: ProblemDetails) -> Response:
    """Serialize a :class:`ProblemDetails` into the canonical RFC 7807 response.

    Single-pass serialization via ``model_dump_json()`` (Pydantic's
    C-accelerated path) avoids the ``model_dump() -> JSONResponse`` two-step.

    ``X-Request-ID`` is intentionally NOT set on typed-handler responses —
    :class:`RequestIdMiddleware` is a pure ASGI middleware that injects the
    header on every response that flows through the user middleware stack.
    Setting it here would produce a duplicated header on the response.
    The catch-all 500 path injects it explicitly because Starlette's
    ``ServerErrorMiddleware`` runs OUTSIDE the user stack.
    """
    return Response(
        content=problem.model_dump_json(),
        status_code=problem.status,
        media_type=PROBLEM_JSON_MEDIA_TYPE,
        headers={"Content-Language": _CONTENT_LANGUAGE},
    )


async def _handle_domain_error(request: Request, exc: Exception) -> Response:
    """Map a :class:`DomainError` to its declared RFC 7807 body and status.

    Also: bind ``error_code`` into the structlog contextvars so the
    middleware's trailing ``request_completed`` log line carries it
    automatically (one-line correlation between "what error fired" and
    "how the request completed"); emit a single ``domain_error_raised``
    INFO line at handler-time so the event is greppable on its own.
    """
    assert isinstance(exc, DomainError)  # noqa: S101 — narrows for static checkers
    request_id, missed_middleware = _resolve_request_id(request)
    structlog.contextvars.bind_contextvars(error_code=exc.code)
    # Branch level on status: 5xx is operator-actionable, 4xx is client-side
    # information; both share the same event name so filters still find them.
    # 5xx ships with exc_info so the traceback survives — a typed 5xx is
    # exactly the case where operators want the original raise site, and
    # without exc_info this is the only place that ever sees the exception
    # (the catch-all unhandled-exception path is bypassed for typed errors).
    is_server_error = exc.http_status >= HTTPStatus.INTERNAL_SERVER_ERROR
    if is_server_error:
        logger.exception("domain_error_raised", code=exc.code, status=exc.http_status)
    else:
        logger.warning("domain_error_raised", code=exc.code, status=exc.http_status)
    problem = _build_problem_payload(exc, request, request_id)
    response = _problem_response(problem)
    _stamp_request_id_header_if_missed(response, request_id, missed=missed_middleware)
    return response


async def _handle_validation_error(request: Request, exc: Exception) -> Response:
    """Map a :class:`RequestValidationError` to ``VALIDATION_FAILED``.

    Each Pydantic error becomes a validated :class:`ValidationErrorDetail`
    instance — running the schema's ``extra='forbid'`` invariant at runtime
    and giving the schema a real consumer (otherwise it would only be an
    OpenAPI surface).

    Pydantic's natural iteration order is preserved (alphabetizing would
    decouple the array from the order the consumer's request listed the
    fields, which is the more useful debugging signal).

    When more than one field fails, the rendered ``detail`` string is
    rewritten to point operators at the array instead of a single field —
    the per-field information is canonical only in ``validation_errors[]``.
    """
    assert isinstance(exc, RequestValidationError)  # noqa: S101 — narrows for static checkers
    request_id, missed_middleware = _resolve_request_id(request)

    raw_errors = exc.errors()
    # Truncate at the handler edge so over-cap inputs (Pydantic's `msg` can
    # interpolate the offending value, especially for `string_too_long` /
    # `union_tag_invalid`) don't trip ValidationErrorDetail's own length cap
    # and explode the handler. The schema cap is the contract; the handler
    # truncation is belt-and-suspenders.
    validation_errors: list[dict[str, Any]] = [
        ValidationErrorDetail(
            field=".".join(str(loc) for loc in e.get("loc", []))[:FIELD_MAX_CHARS],
            reason=str(e.get("msg", "Unknown validation error"))[:REASON_MAX_CHARS],
        ).model_dump(mode="json")
        for e in raw_errors
    ]

    if not validation_errors:
        # Pydantic emitting an empty errors list for a RequestValidationError
        # violates its own invariants — surface it loudly with a bounded
        # triage payload so the operator can reproduce the upstream bug.
        logger.warning(
            "validation_error_with_no_details",
            raw_error_count=len(raw_errors),
            raw_error_types=[type(e).__name__ for e in raw_errors][:5],
        )

    first_field = validation_errors[0]["field"] if validation_errors else "unknown"
    first_reason = validation_errors[0]["reason"] if validation_errors else "unknown"
    domain_err = ValidationFailedError(field=str(first_field), reason=str(first_reason))
    structlog.contextvars.bind_contextvars(error_code=domain_err.code)

    detail_override: str | None = None
    if len(validation_errors) > 1:
        detail_override = (
            f"Validation failed for {len(validation_errors)} fields. "
            "See validation_errors[] for details."
        )

    problem = _build_problem_payload(
        domain_err,
        request,
        request_id,
        detail_override=detail_override,
        extras={"validation_errors": validation_errors},
    )
    response = _problem_response(problem)
    _stamp_request_id_header_if_missed(response, request_id, missed=missed_middleware)
    return response


def _http_status_phrase(status_code: int) -> str:
    """Return the IANA reason phrase for ``status_code``, falling back gracefully."""
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "HTTP Error"


def _http_code_for_status(status_code: int) -> str:
    """Map a raw HTTP status code into a SCREAMING_SNAKE LIP error code.

    For statuses we already model in :mod:`app.exceptions` (404, 500), reuse
    that DomainError's code so the consumer-visible contract stays consistent
    whether the error is raised explicitly or surfaces through Starlette.
    """
    if status_code == HTTPStatus.NOT_FOUND:
        return NotFoundError.code
    if status_code == HTTPStatus.METHOD_NOT_ALLOWED:
        return "METHOD_NOT_ALLOWED"
    if status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return InternalError.code
    return "HTTP_ERROR"


async def _handle_http_exception(request: Request, exc: Exception) -> Response:
    """Wrap an un-typed Starlette/FastAPI :class:`HTTPException` into RFC 7807.

    Starlette raises bare ``HTTPException(404, ...)`` for missing routes
    and ``HTTPException(405, ...)`` for method mismatch — neither is a
    :class:`DomainError`. Without this handler, those would fall through to
    :func:`_handle_unhandled_exception` and emit a misleading 500. We render
    them as RFC 7807 problems with ``type="about:blank"`` per RFC 7807 §4.2
    ("the problem has no additional semantics beyond that of the HTTP status
    code"), preserving the original status and title-from-status-phrase.

    For 404 specifically, we route through :class:`NotFoundError` so the body
    is identical to one produced by ``raise NotFoundError()`` from a route —
    a single source of truth for the 404 wire shape. For other codes we build
    the :class:`ProblemDetails` directly because there is no DomainError that
    matches (e.g. 405, 415).
    """
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 — narrows for static checkers
    request_id, missed_middleware = _resolve_request_id(request)
    status_code = exc.status_code
    status_phrase = _http_status_phrase(status_code)
    detail_text = str(exc.detail) if exc.detail else status_phrase
    code = _http_code_for_status(status_code)
    structlog.contextvars.bind_contextvars(error_code=code)
    if status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        # 5xx HTTPExceptions raised by the framework would otherwise ship
        # without any log line — operators couldn't grep them by request_id.
        logger.warning(
            "http_exception_5xx",
            status_code=status_code,
            detail=detail_text,
        )

    if status_code == HTTPStatus.NOT_FOUND:
        problem = _build_problem_payload(
            NotFoundError(),
            request,
            request_id,
            detail_override=detail_text,
        )
        response = _problem_response(problem)
        _stamp_request_id_header_if_missed(response, request_id, missed=missed_middleware)
        return response

    problem = ProblemDetails(
        type=_ABOUT_BLANK,
        title=status_phrase,
        status=status_code,
        detail=detail_text,
        instance=request.url.path,
        code=code,
        request_id=request_id,
    )
    response = _problem_response(problem)
    _stamp_request_id_header_if_missed(response, request_id, missed=missed_middleware)
    return response


async def _handle_unhandled_exception(request: Request, exc: Exception) -> Response:
    """Map any otherwise-unhandled exception to ``INTERNAL_ERROR`` (HTTP 500).

    The exception type is logged but never serialized into the response body
    (no PII / stack-trace leak). Operators correlate via ``request_id``.
    Method + path are added to the log event so a misbehaving endpoint is
    identifiable from a single log line without reconstructing the request.

    ``X-Request-ID`` is set on the response *here* (not via :class:`RequestIdMiddleware`)
    because Starlette routes ``@app.exception_handler(Exception)`` to
    :class:`ServerErrorMiddleware`, which sits OUTSIDE the user middleware
    stack (always outermost). The RequestIdMiddleware's ``send`` wrapper
    therefore never sees this response, so the header would be missing
    without an explicit injection. Typed handlers (``DomainError``,
    ``RequestValidationError``, ``StarletteHTTPException``) run inside
    :class:`ExceptionMiddleware`, whose responses do flow back through
    RequestIdMiddleware, so they get the header automatically.
    """
    request_id, _missed = _resolve_request_id(request)
    structlog.contextvars.bind_contextvars(error_code=InternalError.code)
    # ``exc_message`` is truncated to 200 chars so triage gets actionable
    # signal without unboundedly serializing input-value snippets. The
    # message never ships to the consumer — only ``InternalError``'s
    # rendered detail does — preserving the wire contract.
    logger.exception(
        "unhandled_exception",
        exc_type=type(exc).__name__,
        exc_message=str(exc)[:200],
    )
    domain_err = InternalError()
    problem = _build_problem_payload(domain_err, request, request_id)
    response = _problem_response(problem)
    response.headers["X-Request-ID"] = request_id
    return response


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app.

    Order is documentation, not semantics: Starlette resolves by walking
    ``type(exc).__mro__`` and picking the most-specific registered handler.
    The DomainError, RequestValidationError, and StarletteHTTPException
    handlers all hit before the catch-all ``Exception`` handler regardless
    of registration order, but listing them in specificity order keeps the
    intent legible.
    """
    app.add_exception_handler(DomainError, _handle_domain_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unhandled_exception)
