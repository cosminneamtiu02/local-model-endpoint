"""Cross-package wire-shape constants shared by ``schemas/`` and consumers.

The module name has no leading underscore (unlike ``app/api/_constants.py``,
which is api-package-internal): this surface is intentionally public —
``app/features/inference/schemas/response_metadata.py`` imports
``REQUEST_ID_LENGTH`` / ``UUID_PATTERN_STR`` from here so the request_id
wire-shape constraints stay in lockstep across the two response envelopes
(and any future sibling that carries a ``request_id`` field). Keeping a
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
``app/api/exception_handlers.py``) match against the same compiled object so
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
:func:`app.api.exception_handlers._bounded_instance`. Hoisted here
(rather than living in two parallel ``Final[int]`` definitions in
``schemas/problem_details.py`` and ``api/exception_handlers.py``) so a
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
