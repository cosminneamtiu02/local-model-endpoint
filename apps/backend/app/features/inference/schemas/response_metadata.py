"""ResponseMetadata wire schema — timing, token, and routing fields."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.dos_caps import MODEL_NAME_MAX_LENGTH, TOKEN_COUNT_MAX
from app.features.inference.model.finish_reason import FinishReason
from app.schemas.wire_constants import REQUEST_ID_LENGTH, UUID_PATTERN_STR


class ResponseMetadata(BaseModel):
    """Response-side metadata block returned alongside generated content.

    The schema is intentionally closed (`extra="forbid"`): adding a new
    field requires a coordinated schema update and consumer redeploy
    rather than a silent drift.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    model: str = Field(
        min_length=1,
        max_length=MODEL_NAME_MAX_LENGTH,
        description="Logical model name resolved from the request envelope.",
    )
    # ``le=TOKEN_COUNT_MAX`` mirrors :class:`OllamaChatResult` so a defective
    # Ollama frame returning a pathologically large ``prompt_eval_count`` /
    # ``eval_count`` is bounded both at the adapter boundary AND at the
    # response-envelope boundary.
    prompt_tokens: int = Field(
        ge=0,
        le=TOKEN_COUNT_MAX,
        description="Tokens consumed by the prompt as reported by the backend.",
    )
    completion_tokens: int = Field(
        ge=0,
        le=TOKEN_COUNT_MAX,
        description="Tokens generated in the completion as reported by the backend.",
    )
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
        description="Request UUID echoed from the X-Request-ID header for log correlation.",
    )
    latency_ms: int = Field(
        ge=0,
        description="Wall-clock latency in milliseconds, measured at the LIP boundary.",
    )
    queue_wait_ms: int = Field(
        ge=0,
        description="Time spent waiting for the in-flight semaphore in milliseconds.",
    )
    finish_reason: FinishReason = Field(
        description="Closed-alphabet reason the backend stopped generating (stop/length/...).",
    )
    # Closed string enum: the only valid backend in v1 is ``ollama``. Widening
    # the type to ``Literal["ollama", "<new>"]`` when a second backend lands
    # is exactly the "coordinated schema update" the class docstring promises;
    # the closed Literal makes a typo (``"olama"``) fail at the wire boundary
    # rather than shipping into consumer routing logic.
    backend: Literal["ollama"] = Field(
        description="Concrete inference backend that served the request (single value in v1).",
    )
