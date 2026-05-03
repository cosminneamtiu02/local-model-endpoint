"""Cross-module constants for the schemas/ package and consumers.

Centralizes the UUID v4 regex pattern used in `ProblemDetails.request_id`,
`ResponseMetadata.request_id`, and the api-layer middleware/handler regex
compilations.
"""

from typing import Final

UUID_PATTERN_STR: Final[str] = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
