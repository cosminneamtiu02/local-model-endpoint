"""Cross-module constants for the schemas/ package and consumers.

Centralizes the UUID v4 regex pattern (and the compiled form) used in
`ProblemDetails.request_id`, `ResponseMetadata.request_id`, and the
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
