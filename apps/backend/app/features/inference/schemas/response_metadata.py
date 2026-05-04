"""ResponseMetadata wire schema — timing, token, and routing fields."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.caps import MODEL_NAME_MAX_LENGTH
from app.features.inference.model.finish_reason import FinishReason
from app.schemas.wire_constants import REQUEST_ID_LENGTH, UUID_PATTERN_STR


class ResponseMetadata(BaseModel):
    """Response-side metadata block returned alongside generated content.

    The schema is intentionally closed (`extra="forbid"`): adding a new
    field requires a coordinated schema update and consumer redeploy
    rather than a silent drift.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    model: str = Field(min_length=1, max_length=MODEL_NAME_MAX_LENGTH)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    # ``UUID_PATTERN_STR`` + ``REQUEST_ID_LENGTH`` mirror :class:`ProblemDetails.request_id`
    # so both response envelopes ship the same OpenAPI ``minLength``/``maxLength``
    # alongside the regex. Pattern alone subsumes the length floors but
    # declaring them explicitly keeps generated-client validators (which
    # read length, not the regex) in lockstep across the success and
    # error envelopes.
    request_id: str = Field(
        pattern=UUID_PATTERN_STR,
        min_length=REQUEST_ID_LENGTH,
        max_length=REQUEST_ID_LENGTH,
    )
    latency_ms: int = Field(ge=0)
    queue_wait_ms: int = Field(ge=0)
    finish_reason: FinishReason
    # Closed string enum: the only valid backend in v1 is ``ollama``. Widening
    # the type to ``Literal["ollama", "<new>"]`` when a second backend lands
    # is exactly the "coordinated schema update" the class docstring promises;
    # the closed Literal makes a typo (``"olama"``) fail at the wire boundary
    # rather than shipping into consumer routing logic.
    backend: Literal["ollama"]
