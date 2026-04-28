"""Pure helpers translating LIP envelope shapes <-> Ollama /api/chat shapes.

Three module-level functions form the entire translation surface:

- `translate_message`  : Message -> Ollama message dict
- `translate_params`   : ModelParams -> Ollama options dict
- `build_chat_result`  : Ollama response JSON -> OllamaChatResult

They are deliberately framework-free (no httpx, no async): unit tests
exercise them directly without transport mocking, and the
`OllamaClient.chat` method composes them around the wire I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from app.features.inference.model.audio_content import AudioContent
from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.ollama_chat_result import OllamaChatResult
from app.features.inference.model.text_content import TextContent

if TYPE_CHECKING:
    from app.features.inference.model.finish_reason import FinishReason
    from app.features.inference.model.message import Message
    from app.features.inference.model.model_params import ModelParams

# Single rename in v1: Ollama calls the max-tokens cap `num_predict`.
# Adding a second entry here is a spec change — update
# graphs/LIP/LIP-E003-F002.md (Scope > params mapping) before extending.
_PARAM_RENAMES: Final[dict[str, str]] = {"max_tokens": "num_predict"}

# Ollama `done_reason` values F002 propagates as-is. Anything outside
# this allowlist (e.g. "unload", missing key, non-string) collapses to
# "stop" — see build_chat_result. Typed with the public FinishReason
# Literal so dict.get(...) narrows to the model's accepted alphabet
# without needing a `# type: ignore` at the OllamaChatResult call site.
# Note: F002 itself never emits "timeout"; that value is set by
# E004-F003 when its asyncio.wait_for budget elapses around the call.
_OLLAMA_TO_LIP_FINISH: Final[dict[str, FinishReason]] = {
    "stop": "stop",
    "length": "length",
}


def translate_message(msg: Message) -> dict[str, Any]:
    """Service Message -> Ollama /api/chat message dict.

    String-content messages pass through unchanged. List-content
    (multimodal) messages are flattened: text parts joined with the
    `\\n\\n` separator, image base64 payloads collected into an `images`
    array on the same message object (Ollama's wire format; URL-only
    `ImageContent` raises NotImplementedError pending pre-encoding by
    an upstream layer), and audio parts deferred until the [UNRESOLVED]
    live-Ollama check is done.
    """
    if isinstance(msg.content, str):
        return {"role": msg.role, "content": msg.content}

    text_parts: list[str] = []
    images: list[str] = []
    # Pyright strict + a closed Literal discriminator make this an
    # exhaustive match: adding a fourth ContentPart variant without
    # extending this block fails type checking, so no silent fallthrough.
    for part in msg.content:
        match part:
            case TextContent():
                text_parts.append(part.text)
            case ImageContent():
                if part.base64 is None:
                    # URL-only ImageContent isn't supported by F002 —
                    # Ollama's /api/chat `images` array expects raw base64
                    # strings, not URLs. The orchestrator/capability layer
                    # should reject or pre-encode URL-only images before
                    # they reach this seam.
                    error_message = (
                        "URL-only ImageContent is [UNRESOLVED] in LIP-E003-F002; "
                        "supply base64 (Ollama /api/chat images expects base64)."
                    )
                    raise NotImplementedError(error_message)
                images.append(part.base64)
            case AudioContent():
                # Spec leaves the Ollama wire shape [UNRESOLVED] until
                # live-Ollama verification with Gemma 4. Fail loud rather
                # than silently dropping the audio payload.
                error_message = (
                    "AudioContent translation is [UNRESOLVED] in LIP-E003-F002; "
                    "Gemma 4 audio wire format pending live-daemon verification."
                )
                raise NotImplementedError(error_message)

    ollama_msg: dict[str, Any] = {"role": msg.role, "content": "\n\n".join(text_parts)}
    if images:
        ollama_msg["images"] = images
    return ollama_msg


def translate_params(params: ModelParams) -> dict[str, Any]:
    """ModelParams -> Ollama options dict.

    Only consumer-set fields are forwarded (via
    `model_dump(exclude_unset=True)`); registry defaults are merged
    upstream by E002-F002. `think` is stripped here because it is
    promoted to a top-level Ollama field by `OllamaClient.chat`,
    not nested in `options`.
    """
    consumer_overrides = params.model_dump(exclude_unset=True)
    consumer_overrides.pop("think", None)
    return {_PARAM_RENAMES.get(k, k): v for k, v in consumer_overrides.items()}


def build_chat_result(response_json: dict[str, Any]) -> OllamaChatResult:
    """Ollama /api/chat JSON response -> OllamaChatResult.

    Reads `message.content` as the canonical answer (`tool_calls` are
    ignored: tools are out of v1 scope, and Gemma 4 may emit them in
    some configurations — `content` is the source of truth either way).
    Token-count keys default to 0 if Ollama omits them; `done_reason`
    falls back to "stop" for anything outside the LIP Literal set.

    Defensive: with `stream=False` Ollama is contractually required to
    return a single terminal frame with `done=True`. A non-terminal
    frame (e.g. proxy hiccup) would otherwise surface as a truncated
    OllamaChatResult; surface the contract violation as a typed error
    that F003's failure-mapping layer can convert to malformed_response.
    """
    if not response_json.get("done", True):
        error_message = "Ollama returned done=False under stream=False; expected terminal frame."
        raise KeyError(error_message)
    raw_finish = response_json.get("done_reason", "stop")
    finish_reason: FinishReason = _OLLAMA_TO_LIP_FINISH.get(raw_finish, "stop")
    return OllamaChatResult(
        content=response_json["message"]["content"],
        prompt_tokens=response_json.get("prompt_eval_count", 0),
        completion_tokens=response_json.get("eval_count", 0),
        finish_reason=finish_reason,
    )
