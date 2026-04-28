"""RFC 7807 problem-details response shape.

This is the canonical wire shape for every error response in LIP.
Replaces the post-bootstrap ``{"error": {...}}`` envelope.

RFC 7807 (https://datatracker.ietf.org/doc/html/rfc7807) standard fields:
    type     — URN identifying the problem type (non-resolvable, per §3.1)
    title    — short human-readable summary
    status   — HTTP status code
    detail   — per-instance human-readable explanation
    instance — request URL path

LIP project extensions (placed at root per RFC 7807's extension convention):
    code        — SCREAMING_SNAKE error code for ergonomic pattern matching
    request_id  — propagated from RequestIdMiddleware

Per-error typed params (e.g. ``max_waiters``, ``current_waiters`` for
``QUEUE_FULL``) and the ``validation_errors`` array for ``VALIDATION_FAILED``
are also placed at root level — that's what ``extra='allow'`` enables.

Asymmetric ``extra`` policy: request envelopes use ``extra='forbid'`` to catch
consumer bugs at the boundary; response envelopes use ``extra='allow'`` to
permit per-error typed extensions per RFC 7807 §3.2.
"""

from pydantic import BaseModel, ConfigDict, Field


class ProblemDetails(BaseModel):
    """RFC 7807 problem-details response body."""

    model_config = ConfigDict(extra="allow")

    type: str = Field(
        description="URN identifying the problem type (non-resolvable per RFC 7807 §3.1)",
    )
    title: str = Field(description="Short human-readable summary of the problem")
    status: int = Field(description="HTTP status code", ge=400, le=599)
    detail: str = Field(description="Per-instance human-readable explanation")
    instance: str = Field(description="The request URL path that produced this problem")
    code: str = Field(description="LIP error code (SCREAMING_SNAKE)")
    request_id: str = Field(description="Request UUID from the X-Request-ID middleware")
