"""RFC 7807 problem-details response shape.

Canonical wire shape for every error response in LIP. Implements RFC 7807
(https://datatracker.ietf.org/doc/html/rfc7807) plus two LIP project
extensions (``code``, ``request_id``) and per-error typed params spread at
root level (RFC 7807 §3.2).

Asymmetric ``extra`` policy: request envelopes use ``extra='forbid'`` to catch
consumer bugs at the boundary; response envelopes use ``extra='allow'`` to
permit per-error typed extensions. Per-field ``Field(description=...)`` strings
are the source of truth for OpenAPI; this docstring stays high-level.

Untrusted-extension warning: some fields reflect raw request input.
``instance`` is the request URL path, and ``validation_errors[].field``
echoes user-supplied field names from the failing payload. Downstream
consumers MUST treat both as untrusted strings — escape on render, never
interpolate into shells, queries, or HTML without sanitization.
"""

from pydantic import BaseModel, ConfigDict, Field


class ProblemDetails(BaseModel):
    """RFC 7807 problem-details response body."""

    model_config = ConfigDict(extra="allow", frozen=True)

    type: str = Field(
        description=(
            "Stable URN identifying the problem type. LIP uses non-resolvable URNs "
            "in v1, deviating from RFC 7807 §3.1's SHOULD-resolve guidance — a "
            "future hosted-docs URL mapping can be introduced without breaking the "
            "URN format."
        ),
    )
    title: str = Field(description="Short human-readable summary of the problem")
    status: int = Field(description="HTTP status code", ge=400, le=599)
    detail: str = Field(description="Per-instance human-readable explanation")
    instance: str = Field(description="The request URL path that produced this problem")
    code: str = Field(description="LIP error code (SCREAMING_SNAKE)")
    request_id: str = Field(
        description="Request UUID from the X-Request-ID middleware",
        min_length=1,
    )
