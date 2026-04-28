"""ResponseMetadata wire schema — eight fields populated by the orchestrator."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResponseMetadata(BaseModel):
    """Response-side metadata block returned alongside generated content.

    The orchestrator (E001-F002) composes these from a mix of:
    - request-id middleware (`request_id`),
    - wall-clock measurements (`latency_ms`, `queue_wait_ms`),
    - the adapter's `OllamaChatResult` (`prompt_tokens`,
      `completion_tokens`, `finish_reason`),
    - the registry-resolved logical `model` and the active `backend`.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    request_id: str
    latency_ms: int = Field(ge=0)
    queue_wait_ms: int = Field(ge=0)
    finish_reason: Literal["stop", "length", "timeout"]
    backend: str
