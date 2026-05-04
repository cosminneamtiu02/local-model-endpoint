"""OllamaChatResult value-object — adapter-side response shape."""

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.caps import CONTENT_MAX_LENGTH, TOKEN_COUNT_MAX
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

    # ``str_strip_whitespace`` is intentionally NOT set on the config: this
    # value-object carries the model's raw generated text. Trimming would
    # silently drop trailing newlines on fenced code blocks (`````\n```) and
    # other deliberate whitespace from the model. ``content`` has no
    # ``min_length=1`` so the strip would serve no defensive purpose either —
    # there is nothing for it to defend against. Sibling user-input schemas
    # (Message text, Settings string fields) opt into the strip per-field
    # via ``StringConstraints`` only where the cap-bypass concern is real.
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str = Field(max_length=CONTENT_MAX_LENGTH)
    prompt_tokens: int = Field(ge=0, le=TOKEN_COUNT_MAX)
    completion_tokens: int = Field(ge=0, le=TOKEN_COUNT_MAX)
    finish_reason: FinishReason = Field(
        description=(
            "stop=natural model halt; length=hit max_tokens; timeout=request budget exceeded."
        ),
    )
