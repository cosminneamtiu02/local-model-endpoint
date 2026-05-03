"""ResponseMetadata wire schema — timing, token, and routing fields."""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.finish_reason import FinishReason

# UUID pattern mirrored from ProblemDetails.request_id and the
# RequestIdMiddleware UUID validator. Defense-in-depth so the response
# envelope can never ship a malformed correlation ID even if a future
# code path builds ResponseMetadata without going through the middleware-
# stamped request_id.
_REQUEST_ID_UUID_PATTERN: Final[str] = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Mirror ``InferenceRequest.model``'s 128-char cap — same logical name flows
# in (request) and out (response), so the bounds should be symmetric.
_MODEL_NAME_MAX_LENGTH: Final[int] = 128


class ResponseMetadata(BaseModel):
    """Response-side metadata block returned alongside generated content.

    The schema is intentionally closed (`extra="forbid"`): adding a new
    field requires a coordinated schema update and consumer redeploy
    rather than a silent drift.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    model: str = Field(min_length=1, max_length=_MODEL_NAME_MAX_LENGTH)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    request_id: str = Field(pattern=_REQUEST_ID_UUID_PATTERN)
    latency_ms: int = Field(ge=0)
    queue_wait_ms: int = Field(ge=0)
    finish_reason: FinishReason
    # Closed string enum: the only valid backend in v1 is ``ollama``. Widening
    # the type to ``Literal["ollama", "<new>"]`` when a second backend lands
    # is exactly the "coordinated schema update" the class docstring promises;
    # the closed Literal makes a typo (``"olama"``) fail at the wire boundary
    # rather than shipping into consumer routing logic.
    backend: Literal["ollama"]
