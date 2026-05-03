"""ResponseMetadata wire schema — timing, token, and routing fields."""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.finish_reason import FinishReason
from app.schemas._constants import UUID_PATTERN_STR

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
    # ``UUID_PATTERN_STR`` is the shared correlation-ID pattern; mirrored
    # here so the response envelope rejects a malformed request_id even
    # if a future code path builds ResponseMetadata without going through
    # the middleware-stamped request_id.
    request_id: str = Field(pattern=UUID_PATTERN_STR)
    latency_ms: int = Field(ge=0)
    queue_wait_ms: int = Field(ge=0)
    finish_reason: FinishReason
    # Closed string enum: the only valid backend in v1 is ``ollama``. Widening
    # the type to ``Literal["ollama", "<new>"]`` when a second backend lands
    # is exactly the "coordinated schema update" the class docstring promises;
    # the closed Literal makes a typo (``"olama"``) fail at the wire boundary
    # rather than shipping into consumer routing logic.
    backend: Literal["ollama"]
