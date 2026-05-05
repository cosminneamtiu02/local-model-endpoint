"""Exception handlers — map errors to RFC 7807 ``application/problem+json``.

structlog binding pattern: this module uses bare ``bind_contextvars`` (not
the context-managed ``bound_contextvars``) for ``error_code`` so the bound
key persists into the middleware's trailing ``request_completed`` log line
— the operator gets one-line correlation between "what error fired" and
"how the request completed" automatically. Cleanup is guaranteed by
:class:`RequestIdMiddleware`'s ``clear_contextvars()`` at the next
request boundary, so the asymmetry vs ``bound_contextvars`` (used in
the middleware itself for ``request_id``/``method``/``path``) is by
design rather than oversight.

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

import itertools
import uuid
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, Final, NamedTuple, cast

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.core.logging import ascii_safe
from app.exceptions import (
    DomainError,
    InternalError,
    MethodNotAllowedError,
    NotFoundError,
    ValidationFailedError,
)
from app.schemas import ProblemDetails, ProblemExtras, ValidationErrorDetail
from app.schemas.validation_error_detail import FIELD_MAX_CHARS, REASON_MAX_CHARS
from app.schemas.wire_constants import (
    ABOUT_BLANK_TYPE,
    CONTENT_LANGUAGE,
    INSTANCE_PATH_MAX_CHARS,
    PROBLEM_JSON_MEDIA_TYPE,
    UUID_REGEX,
)

logger = structlog.get_logger(__name__)

_UNKNOWN_FIELD_SENTINEL: Final[str] = "unknown"
"""Wire-visible sentinel used when the validation handler cannot derive a
field name from Pydantic's error data. Centralized so the three sites that
synthesize "we don't know which field failed" (empty loc, empty errors list,
abnormal-empty-errors fallback) stay in lockstep."""

_DISCRIMINATOR_PREVIEW_MAX_CHARS: Final[int] = 64
"""Cap on each Pydantic error-discriminator string in the abnormal-empty-errors
warning. Symmetric with ``EXC_MESSAGE_PREVIEW_MAX_CHARS`` — keeps a single log
line bounded even if Pydantic ever produces multi-KB ``type`` values."""

_DISCRIMINATOR_LOG_LIMIT: Final[int] = 5
"""Max number of Pydantic error-discriminators to emit in the
abnormal-empty-errors warning. Keeps the operator-facing log line bounded
on a pathological Pydantic upstream regression (the warning is for the
"empty errors list" path, but a future Pydantic bug emitting 10k errors
would otherwise inflate this single warning)."""


def _bounded_instance(request: Request) -> str:
    """Return ``request.url.path`` truncated to ``INSTANCE_PATH_MAX_CHARS``.

    Symmetric with the ``RequestIdMiddleware`` 413 path's ``bounded_path``
    truncation, so both halves of the error envelope (middleware-emitted
    body-too-large + handler-emitted typed errors) ship a uniformly
    bounded ``instance`` field. Sources the cap from
    ``app.schemas.wire_constants`` so a future bump moves both the
    schema's ``max_length`` and this truncation in lockstep — a
    pathological URL well under uvicorn's request-line limit but past
    the schema cap would otherwise fail ProblemDetails construction
    inside an exception handler.
    """
    return request.url.path[:INSTANCE_PATH_MAX_CHARS]


class _RequestIdResolution(NamedTuple):
    """Output of :func:`_resolve_request_id` — id + middleware-missed flag.

    NamedTuple (rather than a bare ``tuple[str, bool]``) so the five
    handler call sites read ``.request_id`` / ``.missed_middleware``
    when they prefer name-access; positional destructure still works
    (``request_id, missed_middleware = _resolve_request_id(request)``)
    so the existing call sites stay terse.
    """

    request_id: str
    missed_middleware: bool


def _resolve_request_id(request: Request) -> _RequestIdResolution:
    """Read the request ID set by :class:`RequestIdMiddleware`.

    Returns ``_RequestIdResolution(request_id, missed_middleware)``. The
    bool is True only on the fallback path so callers can compensate for
    the missing middleware (e.g. explicitly stamp the ``X-Request-ID``
    response header that the middleware would otherwise have set).

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
    # ``isinstance`` narrows ``str`` for pyright; ``UUID_REGEX.match("")``
    # returns ``None`` so the regex alone handles the empty-string case.
    if isinstance(request_id, str) and UUID_REGEX.match(request_id) is not None:
        return _RequestIdResolution(request_id, missed_middleware=False)
    fallback = str(uuid.uuid4())
    # Bind request_id + method + path + phase + a fallback-marker so every
    # subsequent log line for this request carries routing context AND
    # advertises the broken-middleware path. The middleware ordinarily binds
    # all five (request_id, method, path, phase="request", request_id_source);
    # under fallback we duplicate the work so handler-emitted lines don't ship
    # without method/path/phase AND so operators can grep for
    # ``request_id_source=fallback`` to find every log line on the
    # misconfigured-app path. Without ``phase="request"`` here, the
    # documented ``select(.phase == "request")`` jq filter in
    # ``request_id_middleware.py`` would silently drop every fallback-path
    # event — exactly the diagnostic surface that needs maximum visibility.
    structlog.contextvars.bind_contextvars(
        request_id=fallback,
        method=request.method,
        path=request.url.path,
        phase="request",
        request_id_source="fallback",
    )
    # ``path``, ``method``, ``request_id``, and ``phase`` ride in via
    # ``merge_contextvars`` from the bind above; ``request_id_source=
    # "fallback"`` is the discriminator. No additional kwargs needed —
    # passing ``fallback_request_id=fallback`` would duplicate the
    # contextvar-bound ``request_id`` field under a second key.
    logger.warning("request_id_missing_in_state")
    return _RequestIdResolution(fallback, missed_middleware=True)


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


def _build_problem_payload(  # noqa: PLR0913 — ProblemDetails assembly takes typed args (exc + request + 4 wire-shape kwargs); all positional-or-keyword required for readability at every call site.
    exc: DomainError,
    request: Request,
    request_id: str,
    *,
    detail_override: str | None = None,
    extras: ProblemExtras | None = None,
    suppress_typed_params: bool = False,
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

    ``suppress_typed_params=True`` skips the root-level spread of
    ``exc.params`` — used by the multi-error validation path where the
    per-field ``field`` / ``reason`` keys would point at only the FIRST
    error while ``detail`` says "see validation_errors[]".
    """
    spread: dict[str, Any] = (
        exc.params.model_dump(mode="json") if exc.params and not suppress_typed_params else {}
    )
    # ProblemDetails uses ``extra='allow'`` at runtime for typed extension
    # fields. Pydantic-model ``extras`` is dumped (mode='python') so the
    # ``**`` unpack carries the validated typed-extension values without
    # round-tripping through JSON.
    extras_widened: dict[str, Any] = (
        extras.model_dump(mode="python", exclude_none=True) if extras else {}
    )
    # Defense-in-depth: an extras key colliding with a typed spread key would
    # silently win on the ``**`` merge; log + raise loud so the bug surfaces
    # at the handler edge rather than as a confusing wire shape. The raise
    # propagates to ``_handle_unhandled_exception`` which renders a clean
    # InternalError problem+json (its own params/extras have no collisions).
    collisions = spread.keys() & extras_widened.keys()
    if collisions:
        logger.error(
            "problem_details_extras_collision",
            collisions=sorted(collisions),
            original_code=exc.code,
        )
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
            instance=_bounded_instance(request),
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
            type=InternalError.type_uri,
            title=InternalError.title,
            status=InternalError.http_status,
            detail="An unexpected error occurred while building the error response.",
            instance=_bounded_instance(request),
            code=InternalError.code,
            request_id=request_id,
        )


def _problem_response(
    problem: ProblemDetails,
    *,
    extra_headers: Mapping[str, str] | None = None,
) -> Response:
    """Serialize a :class:`ProblemDetails` into the canonical RFC 7807 response.

    Single-pass serialization via ``model_dump_json()`` (Pydantic's
    C-accelerated path) avoids the ``model_dump() -> JSONResponse`` two-step.

    ``extra_headers`` carries framework-supplied response headers that the
    error path must preserve — e.g. Starlette sets ``Allow:`` on 405
    HTTPExceptions, and RFC 9110 §15.5.6 makes that header MANDATORY on
    method-not-allowed responses. The merge is right-biased so caller-
    supplied entries override the static ``Content-Language`` default if a
    future call needs to (none today).

    ``X-Request-ID`` is intentionally NOT set on typed-handler responses —
    :class:`RequestIdMiddleware` is a pure ASGI middleware that injects the
    header on every response that flows through the user middleware stack.
    Setting it here would produce a duplicated header on the response.
    The catch-all 500 path injects it explicitly because Starlette's
    ``ServerErrorMiddleware`` runs OUTSIDE the user stack.
    """
    headers: dict[str, str] = {"Content-Language": CONTENT_LANGUAGE}
    if extra_headers:
        headers.update(extra_headers)
    return Response(
        content=problem.model_dump_json(),
        status_code=problem.status,
        media_type=PROBLEM_JSON_MEDIA_TYPE,
        headers=headers,
    )


async def _handle_domain_error(request: Request, exc: Exception) -> Response:
    """Map a :class:`DomainError` to its declared RFC 7807 body and status.

    Also: bind ``error_code`` into the structlog contextvars so the
    middleware's trailing ``request_completed`` log line carries it
    automatically (one-line correlation between "what error fired" and
    "how the request completed"); emit a single ``domain_error_raised``
    INFO line at handler-time so the event is greppable on its own.
    """
    # ``cast`` (not ``assert``) so the narrowing also holds under ``python -O``
    # where ``assert`` is stripped. Starlette's exception dispatch already
    # routes by ``type(exc).__mro__``, so this typed cast documents the
    # invariant without runtime overhead.
    domain_exc = cast("DomainError", exc)
    # Bind error_code BEFORE _resolve_request_id so the
    # ``request_id_missing_in_state`` warning that may fire from the fallback
    # path inside ``_resolve_request_id`` carries this request's error code.
    # ``domain_exc.code`` is statically known on the registered handler
    # (DomainError subclass invariant), so no constructor can throw between
    # ``cast`` and the bind.
    structlog.contextvars.bind_contextvars(error_code=domain_exc.code)
    request_id, missed_middleware = _resolve_request_id(request)
    # Branch level on status: 5xx is operator-actionable, 4xx is client-side
    # information; both share the same event name so filters still find them.
    # 5xx ships with exc_info so the traceback survives — a typed 5xx is
    # exactly the case where operators want the original raise site, and
    # without exc_info this is the only place that ever sees the exception
    # (the catch-all unhandled-exception path is bypassed for typed errors).
    is_server_error = domain_exc.http_status >= HTTPStatus.INTERNAL_SERVER_ERROR
    if is_server_error:
        # Distinct event name for the 5xx branch so dashboards keying on
        # ``event=domain_error_5xx_raised`` find typed-server-error events
        # without a level-filter join. The 4xx branch keeps the generic
        # ``domain_error_raised`` because client errors don't typically
        # need a separate operator query path. ``status_code`` (not
        # ``status``) so a ``select(.status_code >= 500)`` jq filter
        # matches both this and the framework-5xx branch below.
        logger.exception(
            "domain_error_5xx_raised",
            code=domain_exc.code,
            status_code=domain_exc.http_status,
        )
    else:
        logger.warning(
            "domain_error_raised",
            code=domain_exc.code,
            status_code=domain_exc.http_status,
        )
    problem = _build_problem_payload(domain_exc, request, request_id)
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
    # ``cast`` (not ``assert``) so the narrowing also holds under ``python -O``.
    validation_exc = cast("RequestValidationError", exc)
    # Bind the typed error code into contextvars BEFORE _resolve_request_id
    # (and BEFORE any constructor that could in principle raise) so every
    # log event for this request — including the empty-errors warning below
    # AND the request_id-missing fallback warning — carries
    # error_code=VALIDATION_FAILED for log correlation.
    structlog.contextvars.bind_contextvars(error_code=ValidationFailedError.code)
    request_id, missed_middleware = _resolve_request_id(request)

    # FastAPI's ``RequestValidationError.errors()`` returns the stored
    # ``Sequence[Any]`` (dict-shaped per Pydantic ``ErrorDetails``); unlike
    # the underlying ``pydantic.ValidationError.errors()``, it does not
    # accept ``include_input`` / ``include_url`` / ``include_context``
    # kwargs. Defense against prompt-content interpolation lives in the
    # per-error truncation below (``[:REASON_MAX_CHARS]``) and in the
    # ``ValidationErrorDetail`` schema cap.
    raw_errors = validation_exc.errors()
    # Pydantic's ``ValidationError.errors()[i]`` typed-dict contract guarantees
    # ``loc`` and ``msg`` are present (see Pydantic v2 ``ErrorDetails`` typed
    # dict). Use direct ``[]`` access so a future Pydantic-contract violation
    # surfaces loudly as a real ``KeyError`` we can trace, instead of silently
    # degrading to ``field="unknown"``. Truncate at the handler edge so
    # over-cap inputs (Pydantic's ``msg`` interpolates offending values for
    # ``string_too_long`` / ``union_tag_invalid``) don't trip
    # ValidationErrorDetail's own length cap and explode the handler. The
    # schema cap is the contract; the handler truncation is belt-and-suspenders.
    # Pydantic's ``loc`` tuple includes user-supplied keys when nested-dict
    # validation fails (e.g. ``("body", "metadata", "<user-key>")``). ASCII-
    # replace control chars before truncate, symmetric with the
    # ``request_id_rejected_client_value`` discipline in the middleware:
    # ``application/problem+json`` already defeats browser HTML/JS rendering,
    # but this defends against future ops dashboards that may render
    # ``validation_errors[].field`` into HTML.
    validation_errors: list[ValidationErrorDetail] = [
        ValidationErrorDetail(
            field=ascii_safe(
                ".".join(str(loc) for loc in e["loc"]),
                max_chars=FIELD_MAX_CHARS,
            )
            or _UNKNOWN_FIELD_SENTINEL,
            # Symmetric ASCII-clean on ``reason`` (Pydantic's ``e["msg"]``
            # interpolates user-supplied values into messages, so it's the
            # higher-risk vector for control chars than ``field`` was).
            reason=ascii_safe(str(e["msg"]), max_chars=REASON_MAX_CHARS),
        )
        for e in raw_errors
    ]

    # ``first_field`` / ``first_reason`` are already typed ``str`` from
    # ``ValidationErrorDetail`` (or the literal sentinel) — no ``str()``
    # wrapping needed and the redundant call would mislead a reader into
    # thinking a non-string slipped through.
    first_field = validation_errors[0].field if validation_errors else _UNKNOWN_FIELD_SENTINEL
    first_reason = validation_errors[0].reason if validation_errors else _UNKNOWN_FIELD_SENTINEL
    domain_err = ValidationFailedError(field=first_field, reason=first_reason)
    # Hoist ``len(validation_errors)`` once instead of re-evaluating across
    # the log line, the detail-override branches, and the typed-params
    # suppress flag — symmetric with the surrounding code's
    # hoist-once-then-dispatch idiom (e.g. ``option_keys`` in
    # ``ollama_client.py:366``).
    error_count = len(validation_errors)

    # Symmetric peer of ``domain_error_raised`` (typed 4xx) and
    # ``http_exception_5xx_raised`` (framework 5xx): a single jq filter
    # ``select(.event | endswith("_error_raised"))`` finds every per-error
    # surface uniformly, including the framework-validation 422 path.
    # Without this line, the 422 happy path is greppable only via the
    # contextvar-bound ``error_code=VALIDATION_FAILED`` riding into the
    # ``request_completed`` line — a different filter shape than the
    # other handlers.
    #
    # ``first_field`` / ``first_reason`` carried explicitly so this event is
    # field-set-symmetric with ``domain_error_raised`` and
    # ``http_exception_4xx_raised`` (both ship a triage-actionable preview).
    # Operators triaging a 422 burst from logs alone (without joining the
    # wire body) can distinguish a single-field validation error from
    # consumer-side schema drift via ``error_count`` plus the first-error
    # preview. ``first_reason`` is already truncated to ``REASON_MAX_CHARS``
    # by the schema-side cap above; the ``_DISCRIMINATOR_PREVIEW_MAX_CHARS``
    # cap below is the secondary log-line truncation for compactness.
    logger.warning(
        "validation_error_raised",
        code=ValidationFailedError.code,
        status_code=int(HTTPStatus.UNPROCESSABLE_ENTITY),
        error_count=error_count,
        first_field=first_field,
        first_reason=first_reason[:_DISCRIMINATOR_PREVIEW_MAX_CHARS],
    )

    if not error_count:
        # Pydantic emitting an empty errors list for a RequestValidationError
        # violates its own invariants — surface it loudly with a bounded
        # triage payload so the operator can reproduce the upstream bug.
        # Include content-type / content-length so operators can distinguish
        # "Pydantic upstream bug" from "consumer sent unparseable JSON" or a
        # content-type mismatch. ``ascii_safe`` neutralizes any non-ASCII
        # header bytes so a maliciously crafted header cannot inject
        # control chars into the rendered ConsoleRenderer output.
        raw_content_type = request.headers.get("content-type", "")
        raw_content_length = request.headers.get("content-length", "")
        # Event name uses the ``_missing`` state-form (peer of
        # ``request_id_missing_in_state`` / ``ollama_user_agent_version_missing``)
        # rather than the noun-form ``_anomaly`` — a jq filter
        # ``endswith("_missing")`` then groups all "expected-but-absent"
        # diagnostic surfaces uniformly.
        logger.warning(
            "validation_error_details_missing",
            raw_error_count=len(raw_errors),
            # Pydantic's ``errors()`` returns ``Sequence[ErrorDetails]`` typed
            # dicts; ``type(e).__name__`` would always be the constant
            # ``"dict"``. The ``"type"`` key is the actual discriminator
            # (``string_too_long`` / ``union_tag_invalid`` / ...) operators
            # need to triage the abnormal-empty-errors path.
            raw_error_discriminators=[
                ascii_safe(
                    str(e.get("type", "unknown")),
                    max_chars=_DISCRIMINATOR_PREVIEW_MAX_CHARS,
                )
                for e in itertools.islice(raw_errors, _DISCRIMINATOR_LOG_LIMIT)
            ],
            content_type=ascii_safe(raw_content_type),
            content_length=ascii_safe(raw_content_length),
        )

    detail_override: str | None = None
    if error_count > 1:
        detail_override = (
            f"Validation failed for {error_count} fields. See validation_errors[] for details."
        )
    elif not error_count:
        # Make the abnormal zero-errors path self-documenting on the wire
        # rather than synthesizing a misleading single-field detail.
        detail_override = (
            "Validation failed but per-field details were not produced "
            "(upstream Pydantic emitted no errors)."
        )

    # Suppress typed-params spread except in the canonical single-error
    # case. With 0 errors (Pydantic-bug fallback), the ``field`` / ``reason``
    # keys are the literal sentinel and contradict ``detail``'s "no per-field
    # details were produced" message. With >1 errors they only describe the
    # first error and contradict ``detail``'s "see validation_errors[]"
    # pointer. Suppressing in both abnormal cases keeps the wire body
    # internally consistent. Pass ``validation_errors`` as ``None`` (rather
    # than ``[]``) on the empty path so ``ProblemExtras.model_dump(
    # exclude_none=True)`` drops the key from the wire body — an empty list
    # alongside the "no per-field details were produced" detail message
    # would ship a contradictory wire shape.
    problem = _build_problem_payload(
        domain_err,
        request,
        request_id,
        detail_override=detail_override,
        extras=ProblemExtras(validation_errors=validation_errors or None),
        suppress_typed_params=error_count != 1,
    )
    response = _problem_response(problem)
    _stamp_request_id_header_if_missed(response, request_id, missed=missed_middleware)
    return response


def _http_status_phrase(status_code: int) -> str:
    """Return the IANA reason phrase for ``status_code``, falling back gracefully."""
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        # Control-flow conversion: an unknown status code falls back to a
        # generic phrase. Not a "silent swallow" per CLAUDE.md; the parse
        # failure encodes a known business case (non-IANA status).
        return "HTTP Error"


def _http_code_for_status(status_code: int) -> str:
    """Map a raw HTTP status code into a SCREAMING_SNAKE LIP error code.

    For statuses we already model in :mod:`app.exceptions` (404, 405, 500,
    and the generic 4xx fallback), reuse that DomainError's class-bound code
    so the consumer-visible contract stays consistent whether the error is
    raised explicitly or surfaces through Starlette.
    """
    if status_code == HTTPStatus.NOT_FOUND:
        return NotFoundError.code
    if status_code == HTTPStatus.METHOD_NOT_ALLOWED:
        return MethodNotAllowedError.code
    if status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return InternalError.code
    # ``HTTP_ERROR`` is a string literal, not a class-bound code: there is
    # no DomainError subclass for it because the framework path never
    # raises a typed ``HttpError`` (Starlette emits bare HTTPException for
    # unmodeled 4xx, and this handler wraps them into RFC 7807 with
    # ``type="about:blank"`` per RFC 7807 §4.2). The literal keeps the
    # wire shape stable without inventing a ghost class.
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
    # ``cast`` (not ``assert``) so the narrowing also holds under ``python -O``.
    http_exc = cast("StarletteHTTPException", exc)
    status_code = http_exc.status_code
    # Bind error_code BEFORE _resolve_request_id so the
    # ``request_id_missing_in_state`` warning that may fire from the fallback
    # path inside ``_resolve_request_id`` carries the typed code. Compute the
    # status<400 override up-front so the fallback warning sees the final
    # value rather than the (about-to-be-overridden) HTTP_ERROR sentinel.
    initial_code = (
        InternalError.code
        if status_code < HTTPStatus.BAD_REQUEST
        else _http_code_for_status(status_code)
    )
    structlog.contextvars.bind_contextvars(error_code=initial_code)
    request_id, missed_middleware = _resolve_request_id(request)
    # A non-error HTTPException (status<400) has no place in the RFC 7807
    # envelope (problem+json is for error responses) and would fail the
    # ProblemDetails ``ge=400`` schema constraint. Inline the InternalError
    # synthesis (rather than recursing to ``_handle_unhandled_exception``)
    # so the misconfigured-app path emits one log line and goes through
    # ``_resolve_request_id`` exactly once — recursing would emit
    # ``http_exception_invalid_status_raised`` followed by a misleading
    # ``unhandled_exception`` line referencing the original HTTPException
    # repr (which contains the original non-error status code) and would
    # double-resolve the request_id.
    if status_code < HTTPStatus.BAD_REQUEST:
        # ``error`` (not ``warning``): the wire response is a synthesized 500
        # InternalError, identical in severity to ``http_exception_5xx_raised``
        # below. Operators paging on ``level >= ERROR`` for 5xx misconfiguration
        # would otherwise miss this branch.
        # Truncate ``detail`` to ``REASON_MAX_CHARS`` symmetric with the
        # 5xx/wire-body branches below: an unbounded framework-supplied
        # detail in a structured-log field is the same asymmetry the
        # rest of the schema avoids.
        raw_detail_str = str(http_exc.detail) if http_exc.detail else None
        truncated_detail = raw_detail_str[:REASON_MAX_CHARS] if raw_detail_str else None
        logger.error(
            "http_exception_invalid_status_raised",
            status_code=status_code,
            detail=truncated_detail,
        )
        problem = _build_problem_payload(InternalError(), request, request_id)
        response = _problem_response(problem)
        # Typed-handler responses flow back through RequestIdMiddleware (this
        # handler is registered via ``add_exception_handler``, so Starlette's
        # ExceptionMiddleware — inside the user stack — invokes it). Use the
        # same conditional stamp as the rest of this file: stamp only when
        # the middleware was missed, to avoid duplicating the header.
        _stamp_request_id_header_if_missed(response, request_id, missed=missed_middleware)
        return response
    status_phrase = _http_status_phrase(status_code)
    # Truncate ``detail`` symmetric with ``ValidationErrorDetail.reason``'s
    # 2048-char cap. Starlette today only constructs HTTPException with
    # bounded internal strings, but reflecting an unbounded
    # framework-supplied ``detail`` into the wire body is exactly the
    # asymmetry the rest of the schema avoids.
    raw_detail = str(http_exc.detail) if http_exc.detail else status_phrase
    detail_text = raw_detail[:REASON_MAX_CHARS]
    # Reuse ``initial_code`` computed above — for status>=400 it's the
    # final code (the <400 short-circuit already returned above), so a
    # second ``_http_code_for_status`` call would produce the same value.
    code = initial_code
    if status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        # 5xx HTTPExceptions raised by the framework would otherwise ship
        # without any log line — operators couldn't grep them by request_id.
        # ``logger.exception`` (not ``logger.error``): Starlette dispatches
        # this handler from inside its own ``except`` clause in
        # ``ExceptionMiddleware._handle``, so ``sys.exc_info()`` IS populated
        # here. ``logger.exception`` auto-attaches the framework-side traceback
        # via ``dict_tracebacks`` so operators get the raise-site for free —
        # symmetric with ``domain_error_5xx_raised`` (line 343).
        # ``code`` field-set parity with ``domain_error_5xx_raised`` so
        # ``select(.code == ...)`` queries find both event names.
        logger.exception(
            "http_exception_5xx_raised",
            code=code,
            status_code=status_code,
            detail=detail_text,
        )
    elif status_code >= HTTPStatus.BAD_REQUEST and status_code != HTTPStatus.UNPROCESSABLE_ENTITY:
        # Framework-issued 4xx HTTPExceptions (404 missing route, 405 method
        # mismatch, 415 wrong content-type, etc.) would otherwise ship
        # without any per-error log line — only the trailing
        # ``request_completed`` access-log carries the status. Operators
        # querying ``select(.event | endswith("_raised"))`` for typed errors
        # would miss the framework-4xx surface entirely. ``warning`` (not
        # ``error``): client-side errors aren't operator-actionable in the
        # same way 5xx is. 422 is excluded because
        # ``_handle_validation_error`` owns that path and emits its own
        # ``validation_error_raised`` line.
        logger.warning(
            "http_exception_4xx_raised",
            code=code,
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

    if status_code == HTTPStatus.METHOD_NOT_ALLOWED:
        # Route through MethodNotAllowedError so the wire shape matches a
        # typed ``raise MethodNotAllowedError()`` from a route — single
        # source of truth for the 405 envelope, mirroring the 404 branch.
        # Without this, framework-405 ships ``type="about:blank"`` while
        # typed-405 ships ``type="urn:lip:error:method-not-allowed"`` —
        # consumers pattern-matching on ``type`` would see two URNs for
        # the same ``code=METHOD_NOT_ALLOWED``.
        problem = _build_problem_payload(
            MethodNotAllowedError(),
            request,
            request_id,
            detail_override=detail_text,
        )
        # Starlette's ``Route.handle`` raises ``HTTPException(405,
        # headers={"Allow": ...})`` and the ``Allow`` header is MANDATORY
        # on 405 responses per RFC 9110 §15.5.6 ("the origin server MUST
        # generate an Allow header field in a 405 response"). Forward it
        # through to the wire response — without this, standards-
        # compliant clients (curl --retry, requests Retry adapter) cannot
        # discover supported methods on a 405 and a conformance audit
        # flags LIP as non-compliant.
        response = _problem_response(problem, extra_headers=http_exc.headers)
        _stamp_request_id_header_if_missed(response, request_id, missed=missed_middleware)
        return response

    problem = ProblemDetails(
        type=ABOUT_BLANK_TYPE,
        title=status_phrase,
        status=status_code,
        detail=detail_text,
        instance=_bounded_instance(request),
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
    # Bind the typed error code into contextvars BEFORE resolving the
    # request_id — ``_resolve_request_id`` may itself emit a
    # ``request_id_missing_in_state`` warning on the misconfigured-app
    # path, and that warning should ship with ``error_code=INTERNAL_ERROR``
    # so operators searching by error_code find the broken-middleware
    # diagnostic.
    structlog.contextvars.bind_contextvars(error_code=InternalError.code)
    # ``_resolve_request_id`` returns ``(id, missed)``; this branch always
    # passes ``missed=True`` literally below (ServerErrorMiddleware lives
    # outside the user middleware stack, so the header is always absent).
    # Bind the resolver's ``missed`` flag to ``_missed`` (rather than ``_``)
    # so the comment block on ``_stamp_request_id_header_if_missed`` below
    # can name the variable a future flip would consult.
    request_id, _missed = _resolve_request_id(request)
    # ``internal_error_5xx_raised`` so operator queries align with the
    # typed-domain-error pattern: every 5xx event in the codebase now
    # reads ``*_5xx_raised`` (cf. ``http_exception_5xx_raised``,
    # ``domain_error_5xx_raised``). A jq filter keyed on the ``_5xx_``
    # infix finds the catch-all uniformly with the typed branches.
    #
    # ``logger.exception`` (no explicit ``exc_info=True``): inside an
    # ``except`` block, structlog auto-attaches the traceback via
    # ``dict_tracebacks``. The codebase convention (used here, in
    # ``_handle_domain_error``'s 5xx branch, and in ``ollama_client.chat``'s
    # except) is bare ``logger.exception``; ``logger.critical(..., exc_info=
    # True)`` is the alternative used in ``main.py`` only because operator
    # paging keys on level=CRITICAL there. ``exc_message`` is intentionally
    # NOT serialized: ``str(exc)`` for an arbitrary unhandled exception can
    # carry consumer-supplied prompt content (e.g. a Pydantic ValidationError
    # that escaped the request-validation handler), and the traceback itself
    # already carries the actionable signal for triage.
    #
    # ``method`` and ``path`` flow in via ``merge_contextvars`` from
    # ``RequestIdMiddleware`` (or the fallback bind in
    # ``_resolve_request_id``), but they are also passed explicitly here so
    # the operator can identify the misbehaving endpoint from a single log
    # line even if a future refactor narrows the contextvar lifetime.
    logger.exception(
        "internal_error_5xx_raised",
        exc_type=type(exc).__name__,
        method=request.method,
        path=request.url.path,
    )
    domain_err = InternalError()
    problem = _build_problem_payload(domain_err, request, request_id)
    response = _problem_response(problem)
    # Defense-in-depth: pass ``missed=True`` literally rather than
    # ``missed=_missed`` because ServerErrorMiddleware lives outside the
    # user middleware stack today, so ``X-Request-ID`` is always missing on
    # this path. If a future Starlette release moves catch-all ``Exception``
    # back inside the user stack (encode/starlette#1438/#1715), flip this
    # to ``missed=_missed`` to consult the resolver state. The
    # underscore-prefixed ``_missed`` name above marks the local as
    # intentionally retained for that future flip.
    _stamp_request_id_header_if_missed(response, request_id, missed=True)
    return response


def register_exception_handlers(application: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app.

    Parameter named ``application`` for symmetry with ``register_routers``
    and ``configure_middleware`` — three sibling helpers with one
    parameter convention so the call site in ``app.main.create_app`` reads
    uniformly.

    Order is documentation, not semantics: Starlette resolves by walking
    ``type(exc).__mro__`` and picking the most-specific registered handler.
    The DomainError, RequestValidationError, and StarletteHTTPException
    handlers all hit before the catch-all ``Exception`` handler regardless
    of registration order, but listing them in specificity order keeps the
    intent legible.
    """
    application.add_exception_handler(DomainError, _handle_domain_error)
    application.add_exception_handler(RequestValidationError, _handle_validation_error)
    application.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    application.add_exception_handler(Exception, _handle_unhandled_exception)
