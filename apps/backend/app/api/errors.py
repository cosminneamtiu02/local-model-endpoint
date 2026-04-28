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

import uuid
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import structlog
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.exceptions import DomainError, InternalError, NotFoundError, ValidationFailedError
from app.schemas import ProblemDetails, ValidationErrorDetail

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = structlog.get_logger(__name__)

PROBLEM_JSON_MEDIA_TYPE = "application/problem+json; charset=utf-8"
"""RFC 7807 §3 media type, with explicit UTF-8 charset.

RFC 8259 makes UTF-8 implicit for ``application/json``-style payloads, but
declaring it explicitly disambiguates against legacy proxies and intermediary
caches that historically guessed the charset for unknown ``+json`` suffixes.
"""

_CONTENT_LANGUAGE = "en"
"""RFC 7807 §3.1 advertises the language of ``title`` and ``detail``."""

_ABOUT_BLANK = "about:blank"
"""RFC 7807 §4.2 ``type`` value for HTTP errors with no extra semantics."""


def _resolve_request_id(request: Request) -> str:
    """Read the request ID set by :class:`RequestIdMiddleware`.

    Returning a fallback UUID instead of a static ``"unknown"`` string keeps
    every emitted ``request_id`` field uniformly UUID-shaped, which matters
    for log-correlation tooling that pattern-matches the format. The fallback
    firing means the middleware did not run for this request — a misconfigured
    app, not a normal code path — so we log a structlog warning to make the
    drift visible without crashing the response.
    """
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    fallback = str(uuid.uuid4())
    logger.warning("request_id_missing_in_state", fallback_request_id=fallback)
    return fallback


def _build_problem_payload(
    exc: DomainError,
    request: Request,
    request_id: str,
    *,
    detail_override: str | None = None,
    extras: dict[str, Any] | None = None,
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
    return ProblemDetails(
        type=exc.type_uri,
        title=exc.title,
        status=exc.http_status,
        detail=detail_override if detail_override is not None else exc.detail(),
        instance=request.url.path,
        code=exc.code,
        request_id=request_id,
        **spread,
        **(extras or {}),
    )


def _problem_response(
    problem: ProblemDetails,
    request_id: str,
) -> Response:
    """Serialize a :class:`ProblemDetails` into the canonical RFC 7807 response.

    Single-pass serialization via ``model_dump_json()`` (Pydantic's
    C-accelerated path) avoids the ``model_dump() -> JSONResponse`` two-step,
    and honors any future custom ``@field_serializer`` we add to ``ProblemDetails``
    (which the dict route would silently bypass).
    """
    headers = {
        "Content-Language": _CONTENT_LANGUAGE,
        "X-Request-ID": request_id,
    }
    return Response(
        content=problem.model_dump_json(),
        status_code=problem.status,
        media_type=PROBLEM_JSON_MEDIA_TYPE,
        headers=headers,
    )


# ── Handlers (module-level; registered via add_exception_handler below) ──


async def _handle_domain_error(request: Request, exc: Exception) -> Response:
    """Map a :class:`DomainError` to its declared RFC 7807 body and status."""
    assert isinstance(exc, DomainError)  # noqa: S101 — narrows for static checkers
    request_id = _resolve_request_id(request)
    problem = _build_problem_payload(exc, request, request_id)
    return _problem_response(problem, request_id)


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
    request_id = _resolve_request_id(request)

    raw_errors = exc.errors()
    validation_errors: list[dict[str, Any]] = [
        ValidationErrorDetail(
            field=".".join(str(loc) for loc in e.get("loc", [])),
            reason=str(e.get("msg", "Unknown validation error")),
        ).model_dump(mode="json")
        for e in raw_errors
    ]

    first_field = validation_errors[0]["field"] if validation_errors else "unknown"
    first_reason = validation_errors[0]["reason"] if validation_errors else "unknown"
    domain_err = ValidationFailedError(field=str(first_field), reason=str(first_reason))

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
    return _problem_response(problem, request_id)


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
    request_id = _resolve_request_id(request)
    status_code = exc.status_code
    status_phrase = _http_status_phrase(status_code)
    detail_text = str(exc.detail) if exc.detail else status_phrase

    if status_code == HTTPStatus.NOT_FOUND:
        problem = _build_problem_payload(
            NotFoundError(),
            request,
            request_id,
            detail_override=detail_text,
        )
        return _problem_response(problem, request_id)

    problem = ProblemDetails(
        type=_ABOUT_BLANK,
        title=status_phrase,
        status=status_code,
        detail=detail_text,
        instance=request.url.path,
        code=_http_code_for_status(status_code),
        request_id=request_id,
    )
    return _problem_response(problem, request_id)


async def _handle_unhandled_exception(request: Request, exc: Exception) -> Response:
    """Map any otherwise-unhandled exception to ``INTERNAL_ERROR`` (HTTP 500).

    The exception type is logged but never serialized into the response body
    (no PII / stack-trace leak). Operators correlate via ``request_id``.
    Method + path are added to the log event so a misbehaving endpoint is
    identifiable from a single log line without reconstructing the request.
    """
    request_id = _resolve_request_id(request)
    logger.exception(
        "unhandled_exception",
        request_id=request_id,
        exc_type=type(exc).__name__,
        method=request.method,
        path=request.url.path,
    )
    domain_err = InternalError()
    problem = _build_problem_payload(domain_err, request, request_id)
    return _problem_response(problem, request_id)


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
