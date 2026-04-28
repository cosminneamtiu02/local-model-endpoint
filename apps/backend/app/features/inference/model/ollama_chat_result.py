"""OllamaChatResult value-object — adapter-side response shape."""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.finish_reason import FinishReason

# Upper bound on the response content size held in memory. ``ModelParams.max_tokens``
# has no project-level cap (consumer-supplied; ``gt=0`` only), so a misconfigured
# ``max_tokens=10_000_000`` could otherwise let Ollama generate an unbounded blob
# that lands in this frozen value-object. 1 MiB of text is far above any realistic
# Gemma 4 E2B output (128K tokens ≈ ~512K chars) and below memory-pressure
# territory on the 16 GB M4 host. Belt-and-suspenders alongside the sibling
# string caps (``TextContent.text``, ``ImageContent.url``).
_CONTENT_MAX_LENGTH: Final[int] = 1_048_576


class OllamaChatResult(BaseModel):
    """Intermediate value-object returned by `OllamaClient.chat()`.

    Carries the four fields the adapter can observe directly from
    Ollama's `/api/chat` response. The orchestrator (LIP-E001-F002)
    composes the public `InferenceResponse` from this plus its own
    metadata (`request_id`, `latency_ms`, `queue_wait_ms`, `backend`).
    F002 itself never sets `finish_reason="timeout"`; LIP-E004-F003
    does, when its `asyncio.wait_for` budget elapses around the call.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str = Field(max_length=_CONTENT_MAX_LENGTH)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    finish_reason: FinishReason
