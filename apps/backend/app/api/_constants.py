"""Cross-module constants for the api/ package.

Centralizes string constants used across api/ wire paths (RFC 7807 media
type, Content-Language). The ``EXC_MESSAGE_PREVIEW_MAX_CHARS`` cap lives
in ``app/core/logging.py`` because it is a structlog-side concern, not a
wire-shape concern.
"""

from typing import Final

CONTENT_LANGUAGE: Final[str] = "en"
PROBLEM_JSON_MEDIA_TYPE: Final[str] = "application/problem+json; charset=utf-8"
