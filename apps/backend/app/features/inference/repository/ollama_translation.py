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

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from app.features.inference.model.audio_content import AudioContent
from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.ollama_chat_result import OllamaChatResult
from app.features.inference.model.text_content import TextContent

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from app.features.inference.model.content_part import ContentPart
    from app.features.inference.model.finish_reason import FinishReason
    from app.features.inference.model.message import Message
    from app.features.inference.model.model_params import ModelParams

# Single rename: Ollama calls the max-tokens cap `num_predict`.
# Wrapped in MappingProxyType so the rebind-immutable Final guarantee
# extends to the contained dict — symmetric with the frozen=True value-
# objects in this same feature.
_PARAM_RENAMES: Final[Mapping[str, str]] = MappingProxyType({"max_tokens": "num_predict"})

# Ollama `done_reason` values propagated as-is. Anything outside this
# allowlist (e.g. "unload", missing key, non-string) collapses to "stop"
# — see build_chat_result. Typed with the public FinishReason Literal so
# dict.get(...) narrows to the model's accepted alphabet.
_OLLAMA_TO_LIP_FINISH: Final[Mapping[str, FinishReason]] = MappingProxyType(
    {
        "stop": "stop",
        "length": "length",
    }
)


def _flatten_content_parts(
    parts: Sequence[ContentPart],
) -> tuple[list[str], list[str], list[str]]:
    """Walk a multimodal content list, splitting parts into (text, images, audios)
    base64 buckets. URL-only image/audio parts raise NotImplementedError so an
    upstream layer is forced to pre-encode them.

    Pyright strict + the closed Literal discriminator on ContentPart make the
    match exhaustive: adding a fourth variant without extending this block fails
    type checking, so no silent fallthrough.
    """
    text_parts: list[str] = []
    images: list[str] = []
    audios: list[str] = []
    for part in parts:
        match part:
            case TextContent():
                text_parts.append(part.text)
            case ImageContent():
                if part.base64 is None:
                    error_message = "URL-only ImageContent is not supported; supply base64."
                    raise NotImplementedError(error_message)
                images.append(part.base64)
            case AudioContent():
                if part.base64 is None:
                    error_message = "URL-only AudioContent is not supported; supply base64."
                    raise NotImplementedError(error_message)
                audios.append(part.base64)
    return text_parts, images, audios


def _attach_media_to_message(
    ollama_msg: dict[str, Any],
    role: str,
    images: list[str],
    audios: list[str],
) -> None:
    """Attach images/audios arrays to an Ollama message dict in place. Ollama
    /api/chat documents both arrays only on user/assistant turns; system-role
    media raises so the failure is loud rather than silently dropped."""
    if images:
        if role == "system":
            error_message = (
                "system-role messages with images are not supported by Ollama /api/chat."
            )
            raise NotImplementedError(error_message)
        ollama_msg["images"] = images
    if audios:
        if role == "system":
            error_message = (
                "system-role messages with audios are not supported by Ollama /api/chat."
            )
            raise NotImplementedError(error_message)
        ollama_msg["audios"] = audios


def translate_message(msg: Message) -> dict[str, Any]:
    """Service Message -> Ollama /api/chat message dict.

    String-content messages pass through unchanged. List-content
    (multimodal) messages are flattened: text parts joined with the
    ``\\n\\n`` separator, image/audio base64 payloads collected into
    ``images`` / ``audios`` arrays on the same message object per
    LIP-E003-F002 [RESOLVED].
    """
    if isinstance(msg.content, str):
        return {"role": msg.role, "content": msg.content}

    text_parts, images, audios = _flatten_content_parts(msg.content)
    ollama_msg: dict[str, Any] = {"role": msg.role, "content": "\n\n".join(text_parts)}
    _attach_media_to_message(ollama_msg, msg.role, images, audios)
    return ollama_msg


def translate_params(params: ModelParams) -> dict[str, Any]:
    """ModelParams -> Ollama options dict.

    Only consumer-set fields are forwarded; registry defaults are merged
    upstream. ``think`` rides inside ``options`` alongside the sampling
    fields per LIP-E003-F002 [RESOLVED] (single canonical placement; no
    per-Ollama-version branching).
    """
    consumer_overrides = params.model_dump(exclude_unset=True)
    return {_PARAM_RENAMES.get(k, k): v for k, v in consumer_overrides.items()}


def build_chat_result(response_json: dict[str, Any]) -> OllamaChatResult:
    """Ollama /api/chat JSON response -> OllamaChatResult.

    Reads ``message.content`` as the canonical answer (``tool_calls``
    are ignored — tools are not currently supported, and ``content`` is
    the source of truth either way). Token-count keys default to 0 if
    Ollama omits them; ``done_reason`` falls back to "stop" for anything
    outside the accepted Literal set.

    Defensive: with ``stream=False`` Ollama is contractually required to
    return a single terminal frame with ``done=True``. A non-terminal
    frame (e.g. proxy hiccup) is surfaced as a typed KeyError so the
    failure-mapping layer can convert it to malformed_response.
    """
    if not response_json.get("done", True):
        error_message = "Ollama returned done=False under stream=False; expected terminal frame."
        raise KeyError(error_message)
    raw_finish = response_json.get("done_reason", "stop")
    finish_reason: FinishReason = _OLLAMA_TO_LIP_FINISH.get(raw_finish, "stop")
    # Some Ollama responses (tool-call-only frames) omit content or emit null;
    # OllamaChatResult.content is `str`, so coerce here at the wire boundary
    # rather than letting Pydantic raise a ValidationError outside the failure-
    # mapping seam.
    raw_content = response_json["message"]["content"]
    content = raw_content if isinstance(raw_content, str) else ""
    return OllamaChatResult(
        content=content,
        prompt_tokens=response_json.get("prompt_eval_count", 0),
        completion_tokens=response_json.get("eval_count", 0),
        finish_reason=finish_reason,
    )
