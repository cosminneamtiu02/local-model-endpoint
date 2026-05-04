"""Cross-module constants for the api/ package.

Centralizes string constants used across api/ wire paths (RFC 7807 media
type, Content-Language, the RFC 7807 §4.2 ``about:blank`` sentinel). The
``EXC_MESSAGE_PREVIEW_MAX_CHARS`` cap lives in ``app/core/logging.py``
because it is a structlog-side concern, not a wire-shape concern.
"""

from typing import Final

CONTENT_LANGUAGE: Final[str] = "en"
PROBLEM_JSON_MEDIA_TYPE: Final[str] = "application/problem+json; charset=utf-8"
ABOUT_BLANK_TYPE: Final[str] = "about:blank"
"""RFC 7807 §4.2 ``type`` value for HTTP errors with no extra semantics.

Used by the framework-HTTPException handler (404/405/415/...) and by the
413 short-circuit in :class:`RequestIdMiddleware` for the same reason —
both ship un-typed HTTP errors that have no LIP-specific URN."""
