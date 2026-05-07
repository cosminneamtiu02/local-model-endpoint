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
from app.schemas.problem_extras import VALIDATION_ERRORS_MAX_LENGTH
from app.schemas.validation_error_detail import FIELD_MAX_CHARS, REASON_MAX_CHARS
from app.schemas.wire_constants import (
    ABOUT_BLANK_TYPE,
    CONTENT_LANGUAGE,
    CONTENT_LANGUAGE_HEADER,
    INSTANCE_PATH_MAX_CHARS,
    PROBLEM_JSON_MEDIA_TYPE,
    REQUEST_ID_HEADER,
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
        # ``ascii_safe`` neutralizes log-injection vectors in the
        # decoded path (symmetric with the middleware's bind site —
        # see ``request_id_middleware.py``).
        path=ascii_safe(request.url.path, max_chars=INSTANCE_PATH_MAX_CHARS),
        phase="request",
        request_id_source="fallback",
    )
    # ``path``, ``method``, ``request_id``, and ``phase`` ride in via
    # ``merge_contextvars`` from the bind above; ``request_id_source=
    # "fallback"`` is the discriminator. ``error`` (not ``warning``)
    # because the underlying cause is misconfigured middleware — every
    # subsequent request will hit the same path and the wire response
    # will ship a synthesized fallback UUID that no consumer-side log can
    # correlate against. Sibling diagnostic ``app_state_unavailable`` in
    # ``deps.py`` is also at ``error`` for the same "infrastructure
    # layer didn't run" severity; operator paging on level=error catches
    # both diagnostics uniformly.
    logger.error("request_id_missing_in_state")
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
        response.headers[REQUEST_ID_HEADER] = request_id


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
    # Both spreads use ``mode="json"`` symmetrically so a future ProblemExtras
    # field carrying a non-JSON-primitive (datetime / UUID / Decimal) renders
    # uniformly across typed params and extras. The ``ProblemDetails(extra=
    # "allow")`` model preserves whatever Python value is unpacked into it,
    # so an asymmetric ``mode="python"`` here would land native objects under
    # the typed-spread root keys but JSON-primitives under the extras keys.
    extras_widened: dict[str, Any] = (
        extras.model_dump(mode="json", exclude_none=True) if extras else {}
    )
    # Defense-in-depth: an extras key colliding with a typed spread key would
    # silently win on the ``**`` merge; log + raise loud so the bug surfaces
    # at the handler edge rather than as a confusing wire shape. The raise
    # propagates to ``_handle_unhandled_exception`` which renders a clean
    # InternalError problem+json (its own params/extras have no collisions).
    collisions = spread.keys() & extras_widened.keys()
    if collisions:
        # Hoist ``sorted(collisions)`` once instead of evaluating it twice
        # (log line + error message). Mirrors the ``error_count =
        # len(validation_errors)`` hoist pattern used elsewhere in this
        # module to keep "compute-once, use twice" consistent.
        sorted_collisions = sorted(collisions)
        logger.error(
            "problem_details_extras_collision",
            collisions=sorted_collisions,
            original_code=exc.code,
        )
        # ``raise InternalError() from None`` instead of ``raise
        # RuntimeError(...)``: typed DomainError raises align with the
        # discipline applied everywhere else in the codebase, and the
        # catch-all unhandled-exception path renders the same clean
        # InternalError problem+json wire body regardless. The
        # ``from None`` suppresses the implicit ``__cause__`` so the
        # collision detail does not surface in operator tracebacks
        # (the actionable signal is the ``problem_details_extras_collision``
        # log line above with the sorted collision list, NOT the
        # exception traceback). Wire-body symmetric: both routes
        # produce a clean InternalError envelope via
        # ``_handle_unhandled_exception``.
        raise InternalError from None
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
        # Sanitize the fall-back inputs unconditionally — the ORIGINAL
        # ValidationError above could have been caused by a malformed
        # ``request_id`` (off-pattern UUID) or ``instance`` (path failing
        # the ``^/`` anchor or the 2048-char cap). Re-using those raw
        # values here would re-raise the same ValidationError and the
        # "consumer always gets problem+json" promise would break.
        # ``UUID_REGEX.fullmatch`` defends the known-shape contract; a
        # mismatch synthesizes a fresh UUID4 (bounded random; no
        # consumer-side correlation possible, but neither is the
        # alternative of a bare 500 with no request_id at all). The
        # ``"/"`` literal is the only path string guaranteed to satisfy
        # ProblemDetails' ``instance`` field invariants
        # (``^/`` + 2048 cap), regardless of the inbound request URL.
        safe_request_id = request_id if UUID_REGEX.fullmatch(request_id) else str(uuid.uuid4())
        return ProblemDetails(
            type=InternalError.type_uri,
            title=InternalError.title,
            status=InternalError.http_status,
            detail="An unexpected error occurred while building the error response.",
            instance="/",
            code=InternalError.code,
            request_id=safe_request_id,
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
    headers: dict[str, str] = {CONTENT_LANGUAGE_HEADER: CONTENT_LANGUAGE}
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
    # Slice raw_errors at VALIDATION_ERRORS_MAX_LENGTH BEFORE constructing
    # ValidationErrorDetail entries: the schema-side ``max_length`` cap on
    # ProblemExtras.validation_errors raises ValidationError on >cap, which
    # would escape this handler and surface as INTERNAL_ERROR (a 422 silently
    # demoted to 500 — wrong status, wrong retry semantics). Slicing here
    # makes the wire body a soft truncation: consumers receive the first
    # ``VALIDATION_ERRORS_MAX_LENGTH`` errors, the ``error_count`` log field
    # surfaces the pre-slice total, and the ``detail`` override below names
    # the truncation when it kicks in.
    raw_error_count = len(raw_errors)
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
        for e in raw_errors[:VALIDATION_ERRORS_MAX_LENGTH]
    ]

    # ``first_field`` / ``first_reason`` are already typed ``str`` from
    # ``ValidationErrorDetail`` (or the literal sentinel) — no ``str()``
    # wrapping needed and the redundant call would mislead a reader into
    # thinking a non-string slipped through. Hoist ``first_entry`` once
    # so the truthiness probe + ``[0]`` index are not duplicated across
    # both attribute reads — symmetric with the ``error_count =
    # len(validation_errors)`` hoist below and the
    # ``option_keys_sorted`` hoist in ``OllamaClient.chat``.
    first_entry = validation_errors[0] if validation_errors else None
    first_field = first_entry.field if first_entry else _UNKNOWN_FIELD_SENTINEL
    first_reason = first_entry.reason if first_entry else _UNKNOWN_FIELD_SENTINEL
    domain_err = ValidationFailedError(field=first_field, reason=first_reason)
    # Hoist ``len(validation_errors)`` once instead of re-evaluating across
    # the log line, the detail-override branches, and the typed-params
    # suppress flag — symmetric with the surrounding code's
    # hoist-once-then-dispatch idiom (e.g. the ``option_keys_sorted`` hoist in
    # ``OllamaClient.chat``).
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
    # ``error_count`` is the post-slice count (what ships in the wire body's
    # ``validation_errors[]``); ``raw_error_count`` is the pre-slice total
    # from Pydantic. They differ only when Pydantic produced more than
    # ``VALIDATION_ERRORS_MAX_LENGTH`` errors and the soft-truncation kicked
    # in — operators triaging that case need both values to distinguish "64
    # actual errors" from "64 of N truncated".
    logger.warning(
        "validation_error_raised",
        code=ValidationFailedError.code,
        # ``HTTPStatus.UNPROCESSABLE_ENTITY`` is an ``IntEnum`` (subclass
        # of ``int``); JSONRenderer / orjson serialize it as ``422``
        # natively. The bare value matches the sibling handlers'
        # ``status_code=domain_exc.http_status`` / ``status_code=
        # status_code`` shapes — no ``int(...)`` cast needed.
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        error_count=error_count,
        raw_error_count=raw_error_count,
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
        #
        # ``logger.exception`` (NOT ``logger.warning``) on this branch:
        # the abnormal-empty-errors path IS the "Pydantic upstream bug"
        # 5xx-shaped case in spirit even though the wire status is 422
        # — the framework-side traceback (Pydantic's internal raise
        # site) is the canonical operator-actionable signal, and a
        # warning level without ``exc_info`` would drop it. The 4xx-
        # warning vs 5xx-exception convention used elsewhere in this
        # module is "log the wire-status's level"; this branch
        # deliberately escapes that convention because the abnormal
        # path means the framework lied about its own contract.
        # Sibling 4xx ``warning`` calls (line ~510 above and the
        # http-exception 4xx branch) keep their level — only the
        # framework-bug abnormal path escalates.
        logger.exception(
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
                for e in raw_errors[:_DISCRIMINATOR_LOG_LIMIT]
            ],
            content_type=ascii_safe(raw_content_type),
            content_length=ascii_safe(raw_content_length),
        )

    detail_override: str | None = None
    if error_count > 1:
        # Surface the soft-truncation explicitly when Pydantic emitted more
        # errors than the wire-body cap. Without naming the truncation in
        # ``detail``, a consumer reading "Validation failed for 64 fields"
        # cannot tell whether 64 was the actual count or a ceiling. The
        # ``raw_error_count > error_count`` branch only fires on the
        # truncation path; the canonical case keeps the original prose.
        if raw_error_count > error_count:
            detail_override = (
                f"Validation failed for {raw_error_count} fields "
                f"(first {error_count} included). See validation_errors[] for details."
            )
        else:
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
        # ``validation_errors or None`` — empty list ([]) is falsy in
        # Python, so this returns ``None`` on the empty path; the bridge
        # to ``ProblemExtras.model_dump(exclude_none=True)`` then drops
        # the key from the wire body (an empty list alongside the "no
        # per-field details were produced" detail message would ship a
        # contradictory wire shape). Ruff's SIM222 prefers the ``or``
        # form here.
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
        # ``ascii_safe`` truncates AND scrubs control characters so a future
        # framework-internal ``HTTPException(detail=...)`` carrying a control
        # char (e.g. mid-stream consumer-supplied content-type with raw
        # \x1f) cannot inject ANSI escapes into the dev ConsoleRenderer.
        # Symmetric with the ``ascii_safe`` discipline already used at the
        # ValidationFailedError reason field and the 415-content-type
        # surface in this same module.
        truncated_detail = (
            ascii_safe(str(http_exc.detail), max_chars=REASON_MAX_CHARS)
            if http_exc.detail
            else None
        )
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
    # ``ascii_safe`` (truncate + control-char scrub) symmetric with
    # ``ValidationErrorDetail.reason`` (2048-char cap) and the 415-content-
    # type surface above. Starlette today only constructs HTTPException with
    # bounded literal-internal strings, but reflecting an unbounded or
    # control-char-bearing framework-supplied ``detail`` into the wire body
    # — and into the dev ConsoleRenderer log line — is exactly the
    # asymmetry the rest of the schema avoids.
    raw_detail = str(http_exc.detail) if http_exc.detail else status_phrase
    detail_text = ascii_safe(raw_detail, max_chars=REASON_MAX_CHARS)
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
        # symmetric with ``domain_error_5xx_raised``.
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
        # No ``detail_override``: route through the typed
        # ``NotFoundError().detail()`` so the wire body's ``detail`` matches
        # what a typed ``raise NotFoundError()`` ships ("The requested
        # resource does not exist."). Without this discipline, framework-
        # 404 would ship ``detail="Not Found"`` (Starlette's stock string)
        # while typed-404 ships the typed prose — consumers pattern-
        # matching on ``(type, code, detail)`` would see two surfaces for
        # the same code. The Starlette-supplied detail is still preserved
        # on the log emit above (``detail=detail_text``).
        problem = _build_problem_payload(
            NotFoundError(),
            request,
            request_id,
        )
        response = _problem_response(problem)
        _stamp_request_id_header_if_missed(response, request_id, missed=missed_middleware)
        return response

    if status_code == HTTPStatus.METHOD_NOT_ALLOWED:
        # Route through MethodNotAllowedError so the wire shape matches a
        # typed ``raise MethodNotAllowedError()`` from a route — single
        # source of truth for the 405 envelope (``type``, ``title``,
        # ``code``, ``status``, AND ``detail``), mirroring the 404 branch.
        # Without this, framework-405 ships ``type="about:blank"`` while
        # typed-405 ships ``type="urn:lip:error:method-not-allowed"`` —
        # consumers pattern-matching on ``type`` would see two URNs for
        # the same ``code=METHOD_NOT_ALLOWED``. The Starlette-supplied
        # detail is preserved on the log emit above.
        problem = _build_problem_payload(
            MethodNotAllowedError(),
            request,
            request_id,
        )
        # Starlette's ``Route.handle`` raises ``HTTPException(405,
        # headers={"Allow": ...})`` and the ``Allow`` header is MANDATORY
        # on 405 responses per RFC 9110 §15.5.6 ("the origin server MUST
        # generate an Allow header field in a 405 response"). Forward it
        # through to the wire response — without this, standards-
        # compliant clients (curl --retry, requests Retry adapter) cannot
        # discover supported methods on a 405 and a conformance audit
        # flags LIP as non-compliant.
        #
        # Defensive log: if app code ever raises a typed
        # ``HTTPException(405)`` without ``headers={"Allow": ...}``, the
        # framework-auto-405 path's ``Allow`` guarantee no longer holds
        # and the wire response would silently violate RFC 9110 §15.5.6.
        # This emit surfaces the conformance gap so an operator can
        # trace it back to the offending raise site. Today no app code
        # raises ``HTTPException(405)`` (typed ``MethodNotAllowedError``
        # is the project's blessed surface, and Starlette's auto-405 for
        # method-mismatch always sets ``Allow``), so the warning fires
        # only on the regression-class.
        if http_exc.headers is None or "allow" not in {k.lower() for k in http_exc.headers}:
            # ``method=request.method`` (no ``ascii_safe`` wrap) mirrors
            # the existing access-log pattern at line 183 / 972 — the
            # method is one of a closed alphabet (GET/POST/PUT/...) by
            # the time it reaches the handler chain (Starlette rejects
            # malformed methods earlier).
            logger.warning(
                "http_exception_405_missing_allow_header",
                phase="request",
                method=request.method,
                path=_bounded_instance(request),
            )
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
    # ``_resolve_request_id`` returns ``(id, missed)``; the resolver hits
    # ``request.state.request_id`` (populated by ``RequestIdMiddleware``
    # on the request side) so ``missed`` is False on the happy path. The
    # response from this catch-all handler, however, flows OUT through
    # ``ServerErrorMiddleware`` (outside the user middleware stack), NOT
    # back through ``RequestIdMiddleware`` — so the response always
    # arrives at the client without an ``X-Request-ID`` header unless we
    # stamp it explicitly below. The ``missed`` bool is captured but not
    # consulted: this is THE one path where we always stamp regardless of
    # request-side middleware state. Future Starlette change
    # (encode/starlette#1438 / encode/starlette#1715) that moves the
    # catch-all inside the user stack would change this — flip the
    # ``missed=True`` literal below to ``missed=missed_middleware`` in
    # that PR.
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
        # ``code`` + ``status_code`` for field-set parity with
        # ``domain_error_5xx_raised`` and ``http_exception_5xx_raised``
        # so a jq filter ``select(.event | endswith("_5xx_raised")) |
        # .code`` finds string values uniformly across all three 5xx
        # branches — instead of ``null`` here vs. typed values on the
        # typed branches.
        code=InternalError.code,
        status_code=int(HTTPStatus.INTERNAL_SERVER_ERROR),
        exc_type=type(exc).__name__,
        method=request.method,
        # ``ascii_safe`` neutralizes log-injection vectors in the decoded
        # path (symmetric with the middleware bind and the fallback
        # ``_resolve_request_id`` bind above).
        path=ascii_safe(request.url.path, max_chars=INSTANCE_PATH_MAX_CHARS),
    )
    domain_err = InternalError()
    problem = _build_problem_payload(domain_err, request, request_id)
    response = _problem_response(problem)
    # ``missed=True`` is hard-coded here because ServerErrorMiddleware
    # lives outside the user middleware stack today — the response goes
    # back to the client without re-entering ``RequestIdMiddleware``, so
    # the header is always missing on this catch-all path regardless of
    # whether the request side stamped it. If encode/starlette#1438 /
    # encode/starlette#1715 ever move this handler back inside the user
    # stack, flip to ``missed=_missed`` so the resolver's flag prevents
    # a duplicate stamp.
    _stamp_request_id_header_if_missed(response, request_id, missed=True)
    return response


def register_exception_handlers(application: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app.

    Order is documentation, not semantics: Starlette resolves by walking
    ``type(exc).__mro__`` and picking the most-specific registered handler.
    The DomainError, RequestValidationError, and StarletteHTTPException
    handlers all hit before the catch-all ``Exception`` handler regardless
    of registration order, but listing them in specificity order keeps the
    intent legible.

    The catch-all is registered against ``Exception`` (NOT
    ``BaseException``). ``BaseException``-derived errors that are not
    ``Exception``-derived — ``KeyboardInterrupt``, ``SystemExit``,
    ``GeneratorExit``, and ``asyncio.CancelledError`` (per Python
    3.11+) — escape this handler and surface as Starlette's
    ``ServerErrorMiddleware`` bare 500. The
    ``RequestIdMiddleware._resolve_access_log_status`` discipline
    surfaces those as ``status_code=499`` (CancelledError — nginx
    Client Closed Request sentinel) or ``=500`` (the others), so the
    access-log surface preserves the operator-actionable signal even
    though the wire body is not problem+json on that path. Inverting
    to ``BaseException`` would produce problem+json on
    ``KeyboardInterrupt``/``SystemExit``, but that is the wrong
    optimisation: those signals mean the process is dying, and a
    process about to exit emitting a wire envelope is purely
    cosmetic — and a cancellation handler that emits a body would
    swallow the cancellation propagation that releases LIP-E001-F002's
    in-flight semaphore slot.
    """
    application.add_exception_handler(DomainError, _handle_domain_error)
    application.add_exception_handler(RequestValidationError, _handle_validation_error)
    application.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    application.add_exception_handler(Exception, _handle_unhandled_exception)
