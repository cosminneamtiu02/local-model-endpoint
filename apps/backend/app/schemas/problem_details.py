"""RFC 7807 problem-details response shape.

Canonical wire shape for every error response in LIP. Implements RFC 7807
(https://datatracker.ietf.org/doc/html/rfc7807) plus two LIP project
extensions (``code``, ``request_id``) and per-error typed params spread at
root level (RFC 7807 §3.2).

LIP-specific narrowings vs RFC 7807 (the spec permits looser shapes; LIP
narrows them for wire-contract clarity):

- ``type``: restricted to ``about:blank`` or ``urn:lip:error:<code-kebab>``.
  RFC 7807 §3.1 says "SHOULD be a URI" but permits any URI (including http
  URLs). LIP's URN-only narrowing gives consumers a stable pattern to
  match without coupling to a hosted-docs URL.
- ``instance``: must start with ``/``. RFC 7807 §3.1 permits any URI
  reference; LIP commits to the URL-path subset because every emitter
  populates it from ``request.url.path``.
- ``status``: 400-599 only (RFC 7807 §3.1 says SHOULD be the HTTP status,
  but does not strictly forbid non-error codes; LIP forbids them since
  problem+json is for error responses).

``extra='allow'`` is required because per-error typed params and
ProblemExtras keys (e.g. ``validation_errors``) are spread at root level
(RFC 7807 §3.2). Per-field ``Field(description=...)`` strings are the
source of truth for OpenAPI; this docstring stays high-level.

Untrusted-extension warning: some fields reflect raw request input.
``instance`` is the request URL path, and ``validation_errors[].field``
echoes user-supplied field names from the failing payload. Downstream
consumers MUST treat both as untrusted strings — escape on render, never
interpolate into shells, queries, or HTML without sanitization.
"""

import re
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.wire_constants import (
    ABOUT_BLANK_TYPE,
    INSTANCE_PATH_MAX_CHARS,
    REQUEST_ID_LENGTH,
    UUID_PATTERN_STR,
)

# Per-string length caps, symmetric with ValidationErrorDetail's
# field=512 / reason=2048 caps. Bounds response amplification on the
# error path: an upstream Ollama failure interpolated into ``detail``
# could otherwise ship multi-KB problem+json bodies.
_TITLE_MAX_CHARS: Final[int] = 128
_DETAIL_MAX_CHARS: Final[int] = 4096
_CODE_MAX_CHARS: Final[int] = 128
# Longest realistic URN form: ``urn:lip:error:`` (14 chars) + ~100 chars
# of kebab tail. 160 is a comfortable ceiling.
_TYPE_MAX_CHARS: Final[int] = 160


class ProblemDetails(BaseModel):
    """RFC 7807 problem-details response body."""

    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    type: str = Field(
        description=(
            "Stable URN identifying the problem type. LIP uses non-resolvable URNs "
            "in v1, deviating from RFC 7807 §3.1's SHOULD-resolve guidance — a "
            "future hosted-docs URL mapping can be introduced without breaking the "
            "URN format."
        ),
        # Pin the format the handler actually produces: ``about:blank`` for
        # framework-level HTTP errors (RFC 7807 §4.2) or ``urn:lip:error:<code>``
        # for typed DomainErrors. A direct ``ProblemDetails(type="oops", ...)``
        # construction now fails the schema instead of shipping a body that
        # violates the URN convention consumers pattern-match on. The
        # ``about:blank`` literal is sourced from ``wire_constants`` so the
        # schema regex and the framework-HTTPException handler emit-site
        # cannot drift apart. ``re.escape`` defends against a future
        # ``ABOUT_BLANK_TYPE`` value that introduces a regex metachar
        # (``.``, ``+``, ``?``, ``*``, ``(``, ``)``, ``|``, ``\``) — today
        # ``"about:blank"`` is regex-safe so the escape is a no-op, but
        # the no-op makes the anti-drift contract mechanical.
        pattern=rf"^({re.escape(ABOUT_BLANK_TYPE)}|urn:lip:error:[a-z0-9-]+)$",
        # Explicit ``min_length=1`` symmetric with the sibling
        # ``title``/``detail``/``instance`` fields so OpenAPI consumers
        # reading ``minLength`` (not the regex) enforce non-empty
        # client-side per the documented "OpenAPI sync" rationale on
        # ``request_id`` below.
        min_length=1,
        max_length=_TYPE_MAX_CHARS,
    )
    title: str = Field(
        description="A short human-readable summary of the problem.",
        min_length=1,
        max_length=_TITLE_MAX_CHARS,
    )
    status: int = Field(description="HTTP status code.", ge=400, le=599)
    detail: str = Field(
        description="Per-instance human-readable explanation.",
        min_length=1,
        max_length=_DETAIL_MAX_CHARS,
    )
    instance: str = Field(
        description="The request URL path that produced this problem.",
        # Pin URL-path form: every handler populates this from
        # ``request.url.path`` which is Starlette-guaranteed to start with
        # ``/``. RFC 7807 §3.1 permits any URI reference, but LIP's wire
        # contract is the URL-path subset; the pattern documents and
        # enforces that commitment so a hand-rolled construction in tests
        # / future helpers cannot ship a malformed ``instance``. The
        # ``max_length`` is defense-in-depth on the wire schema — the
        # middleware truncates path previews in logs but the schema is
        # the last line keeping multi-KB ``instance`` strings off the wire.
        min_length=1,
        max_length=INSTANCE_PATH_MAX_CHARS,
        pattern=r"^/",
    )
    code: str = Field(
        description="LIP error code (SCREAMING_SNAKE).",
        # Mirror the SCREAMING_SNAKE invariant the codegen validator
        # already enforces on errors.yaml — defense-in-depth so a future
        # contributor adding an HTTPException-status-to-code mapping with
        # a kebab/camel value fails at the schema, not silently on the wire.
        # The pattern forbids leading/trailing underscores, double
        # underscores, AND digit-only segments after the first letter
        # (e.g. ``X_42`` is rejected) so codegen and the wire schema agree
        # on the canonical form.
        pattern=r"^[A-Z][A-Z0-9]*(_[A-Z][A-Z0-9]*)*$",
        # Explicit ``min_length=1`` symmetric with the sibling text
        # fields so OpenAPI consumers reading ``minLength`` (not the
        # regex) enforce non-empty client-side per the documented
        # "OpenAPI sync" rationale on ``request_id`` below.
        min_length=1,
        max_length=_CODE_MAX_CHARS,
    )
    request_id: str = Field(
        description="Request UUID from the X-Request-ID middleware.",
        # Mirror the UUID-shape invariant the middleware + handler both
        # enforce — defense-in-depth so a future code path that builds
        # ProblemDetails without going through ``_resolve_request_id``
        # (e.g. a synthetic test fixture leaking into production helpers)
        # cannot ship a malformed correlation ID. Pattern subsumes the
        # length floors but the explicit min/max keeps OpenAPI docs and
        # static-analysis caps in sync.
        pattern=UUID_PATTERN_STR,
        min_length=REQUEST_ID_LENGTH,
        max_length=REQUEST_ID_LENGTH,
    )
