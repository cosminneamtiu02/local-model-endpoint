"""OllamaChatResult value-object — adapter-side response shape."""

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.finish_reason import FinishReason


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

    content: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    finish_reason: FinishReason
