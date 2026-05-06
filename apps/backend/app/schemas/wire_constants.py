"""Cross-package wire-shape constants shared by ``schemas/`` and consumers.

The module name has no leading underscore: this surface is intentionally
public — ``app/features/inference/schemas/response_metadata.py`` imports
``REQUEST_ID_LENGTH`` / ``UUID_PATTERN_STR`` from here so the request_id
wire-shape constraints stay in lockstep across the two response envelopes
(and any future sibling that carries a ``request_id`` field), while the
api/middleware layer reads ``CONTENT_LANGUAGE`` / ``PROBLEM_JSON_MEDIA_TYPE``
to emit RFC 7807 problem+json with the canonical wire shape. Keeping a
``_`` prefix would mislabel the visibility scope and invite a contributor
to mistakenly duplicate the constants in their own feature module.

Centralizes the UUID v4 regex pattern (and the compiled form) used in
``ProblemDetails.request_id``, ``ResponseMetadata.request_id``, and the
api-layer middleware/handler regex matches.
"""

import re
from typing import Final

UUID_PATTERN_STR: Final[str] = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
UUID_REGEX: Final[re.Pattern[str]] = re.compile(UUID_PATTERN_STR, re.IGNORECASE)
"""Pre-compiled case-insensitive UUID regex shared across api/ and schemas/.

Both :class:`RequestIdMiddleware` and :func:`_resolve_request_id` (in
``app/api/exception_handler_registry.py``) match against the same compiled object so
a future pattern change (e.g. adding ``re.UNICODE``) cannot drift between
the two sites; centralization also avoids a per-process duplicate
``re.compile`` cost at import time."""

REQUEST_ID_LENGTH: Final[int] = 36
"""Canonical UUID-string length (8-4-4-4-12 hex + 4 dashes).

Hoisted out of ``schemas.problem_details`` so the wire schemas
(:class:`ProblemDetails`, :class:`ResponseMetadata`, and any future
sibling that carries a ``request_id`` field) all source the same length
constraint. The pattern alone subsumes the length but declaring
min/max explicitly keeps OpenAPI consumers (which read ``minLength``/
``maxLength`` from the schema, not the regex) in lockstep across the
two response envelopes."""

INSTANCE_PATH_MAX_CHARS: Final[int] = 2048
"""Cap for ``ProblemDetails.instance`` and the matching truncation in
:func:`app.api.exception_handler_registry._bounded_instance`. Hoisted here
(rather than living in two parallel ``Final[int]`` definitions in
``schemas/problem_details.py`` and ``api/exception_handler_registry.py``) so a
future bump moves both sites in lockstep — the handler's truncation
must always match the schema's ``max_length`` or a 2049-char path would
trip ``ProblemDetails`` construction inside the very handler that's
trying to render it."""

ABOUT_BLANK_TYPE: Final[str] = "about:blank"
"""RFC 7807 §4.2 ``type`` value for HTTP errors with no extra semantics.

Used by the framework-HTTPException handler (404/405/415/...) and by the
413 short-circuit in :class:`RequestIdMiddleware` for the same reason —
both ship un-typed HTTP errors that have no LIP-specific URN. Co-located
with the other wire-shape constants so the ``ProblemDetails.type``
regex can build itself from the same literal that the handlers emit
(no risk of the regex and the emit-site drifting apart)."""

REQUEST_ID_HEADER: Final[str] = "X-Request-ID"
"""Canonical wire spelling of the request-id header.

``RequestIdMiddleware`` emits the lowercase byte form (``b"x-request-id"``)
on the response side — HTTP/1.1 headers are case-insensitive, so the
distinction is presentation-only — but every consumer-facing reference
(test helpers, contract tests, OpenAPI doc strings) reads this constant
to defeat literal-vs-literal drift the same way the rest of
``wire_constants`` defeats UUID-regex drift."""

CONTENT_LANGUAGE_HEADER: Final[str] = "Content-Language"
"""Canonical wire spelling of the Content-Language header NAME.

Symmetric with :data:`REQUEST_ID_HEADER` — every emit site reads this
constant rather than hard-coding the literal so a future i18n bump that
adds content negotiation is a single-line edit at this module rather
than a grep across the api/ + schemas/ tree. ``RequestIdMiddleware``
emits the lowercase byte form (``b"content-language"``) on the 413 ASGI
short-circuit; HTTP headers are case-insensitive so the byte/string
duality is presentation-only."""

CONTENT_LANGUAGE: Final[str] = "en"
"""RFC 7807 §3.1 ``Content-Language`` header VALUE emitted on every
problem+json response. v1 wire contract is "the response is English-only";
when i18n arrives in a future milestone, this becomes content-negotiated."""

PROBLEM_JSON_MEDIA_TYPE: Final[str] = "application/problem+json; charset=utf-8"
"""RFC 7807 §3 media-type emitted on every error response and on the 413
short-circuit body in :class:`RequestIdMiddleware`. Co-located with the
other wire-shape constants here so a future ``ProblemDetails`` schema-side
validator pinning the media type can read it from the same module that
the emit sites do — single source of truth for the wire content type."""
