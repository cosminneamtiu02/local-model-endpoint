"""Cross-module constants for the api/ package.

Centralizes string constants used across api/ wire paths (RFC 7807 media
type, Content-Language). The ``EXC_MESSAGE_PREVIEW_MAX_CHARS`` cap lives
in ``app/core/logging.py`` because it is a structlog-side concern, not a
wire-shape concern. ``ABOUT_BLANK_TYPE`` and ``INSTANCE_PATH_MAX_CHARS``
live in ``app/schemas/wire_constants.py`` (per ADR-014) because they are
wire-shape concerns shared with the ``ProblemDetails`` schema regex /
``max_length``; co-locating them with the schema constants prevents a
drift where the handler's emit-site value diverges from the schema's
validation pattern.
"""

from typing import Final

CONTENT_LANGUAGE: Final[str] = "en"
PROBLEM_JSON_MEDIA_TYPE: Final[str] = "application/problem+json; charset=utf-8"
