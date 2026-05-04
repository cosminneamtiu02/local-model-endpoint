"""Pure helpers translating LIP envelope shapes <-> Ollama /api/chat shapes.

Three module-level functions form the entire translation surface:

- `translate_message`  : Message -> Ollama message dict
- `translate_params`   : ModelParams -> Ollama options dict
- `build_chat_result`  : Ollama response JSON -> OllamaChatResult

They are deliberately framework-free (no httpx, no async): unit tests
exercise them directly without transport mocking, and the
`OllamaClient.chat` method composes them around the wire I/O.

Lives under ``model/`` (not ``repository/``) since it is pure value-object
construction — the layering rule "repository -> model" applies one way:
``OllamaClient.chat`` imports these helpers, never the inverse.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, cast

import structlog

from app.features.inference.model.audio_content import AudioContent
from app.features.inference.model.finish_reason import FinishReason
from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.ollama_chat_result import OllamaChatResult
from app.features.inference.model.text_content import TextContent

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.features.inference.model.content_part import ContentPart
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
    parts: "Sequence[ContentPart]",
) -> tuple[list[str], list[str], list[str]]:
    """Split a multimodal content list into (text, images, audios) base64 buckets.

    URL-only image/audio parts raise NotImplementedError so an upstream
    layer is forced to pre-encode them.

    Pyright strict + the closed Literal discriminator on ContentPart make
    the match exhaustive: adding a fourth variant without extending this
    block fails type checking, so no silent fallthrough.
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
    """Attach images/audios arrays to an Ollama message dict in place.

    Ollama /api/chat documents both arrays only on user/assistant turns;
    system-role media raises so the failure is loud rather than silently
    dropped. The two media kinds share an identical attach contract — a
    tuple loop expresses the rule once so a future media-kind addition is
    a single-line change.
    """
    for media, key in ((images, "images"), (audios, "audios")):
        if not media:
            continue
        if role == "system":
            error_message = (
                f"system-role messages with {key} are not supported by Ollama /api/chat."
            )
            raise NotImplementedError(error_message)
        ollama_msg[key] = media


def translate_message(msg: "Message") -> dict[str, Any]:
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
    # Ollama /api/chat exposes ``content`` as a single string (no rich-parts
    # array on the wire). Two-newline join keeps the resulting prompt
    # human-readable when several text parts share a turn, per LIP-E003-F002
    # [RESOLVED]; the choice is documented here so a reader looking at the
    # wire dump can match it back to the source-of-truth decision.
    ollama_msg: dict[str, Any] = {"role": msg.role, "content": "\n\n".join(text_parts)}
    _attach_media_to_message(ollama_msg, msg.role, images, audios)
    return ollama_msg


def translate_params(params: "ModelParams") -> dict[str, Any]:
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
    frame, missing ``message`` field, or non-dict ``message`` value is
    surfaced as a typed ``ValueError`` so the failure-mapping layer can
    convert it to ``malformed_response`` uniformly. ``ValueError`` (not
    ``KeyError``) matches Python's data model convention — ``KeyError``
    is reserved for genuine mapping-key misses, so collapsing real key
    errors into the malformed-frame signal would be ambiguous.

    No ``ollama_response_malformed`` log line is emitted from these
    branches: the downstream ``OllamaClient.chat`` ``except Exception``
    arm's ``ollama_call_failed`` line carries ``exc_message=`` with the
    same diagnostic string ("non terminal frame", "missing 'message'
    field", etc.). Logging here would double-count the same failure —
    same convention as ``_decode_ollama_json`` in ollama_client.py.
    """
    if not response_json.get("done", True):
        error_message = (
            "Ollama malformed frame: done=False under stream=False; expected terminal frame."
        )
        raise ValueError(error_message)
    raw_finish = response_json.get("done_reason", "stop")
    finish_reason: FinishReason = _OLLAMA_TO_LIP_FINISH.get(raw_finish, "stop")
    if "message" not in response_json:
        error_message = "Ollama malformed frame: response missing 'message' field."
        raise ValueError(error_message)
    raw_message_value: Any = response_json["message"]
    # The annotation on ``response_json`` types this as Any; runtime-check the
    # message is actually a dict so a future Ollama protocol drift (``message``
    # as null/list/string) surfaces as a typed malformed-frame ValueError
    # instead of a TypeError ("None is not subscriptable") that the
    # failure-mapping layer would not recognize.
    if not isinstance(raw_message_value, dict):
        error_message = (
            "Ollama malformed frame: 'message' field has non-object type "
            f"{type(raw_message_value).__name__}."
        )
        # ``ValueError`` (not the TRY004-preferred ``TypeError``) keeps every
        # malformed-Ollama-frame case routed through one exception type
        # the failure-mapping layer (LIP-E003-F003) catches uniformly.
        raise ValueError(error_message)  # noqa: TRY004 — unified malformed-frame signal
    # ``cast`` (not a typed assignment) because ``raw_message_value`` came in
    # as ``Any``; isinstance narrows to ``dict[Unknown, Unknown]`` which
    # pyright strict still flags. The cast is safe (we just isinstance-checked
    # ``dict`` and Ollama's wire format guarantees str keys); the dict entry
    # accesses below preserve the per-key type discipline.
    raw_message: dict[str, Any] = cast("dict[str, Any]", raw_message_value)
    if "content" not in raw_message:
        error_message = "Ollama malformed frame: message missing 'content' field."
        raise ValueError(error_message)
    raw_content = raw_message["content"]
    # ``isinstance`` coerces ``None`` / non-str values to an empty string so
    # OllamaChatResult.content (typed ``str``) doesn't fail Pydantic validation
    # outside the seam.
    content = raw_content if isinstance(raw_content, str) else ""
    # Tool-calls land on a non-tools-aware model only via a registry update
    # to a tool-capable model. Today's models (Gemma 4 E2B) don't emit them,
    # but warning when the frame appears keeps the silent-drop observable
    # so an operator notices the model upgrade before puzzling over an
    # empty content string. Single ``.get`` then narrow — avoids the prior
    # double-lookup pattern (LBYL via .get + EAFP via [...]).
    candidate = raw_message.get("tool_calls")
    tool_calls: list[object] | None = (
        cast("list[object]", candidate) if isinstance(candidate, list) else None
    )
    if tool_calls:
        logger.warning("ollama_tool_calls_ignored", count=len(tool_calls))
    return OllamaChatResult(
        content=content,
        prompt_tokens=response_json.get("prompt_eval_count", 0),
        completion_tokens=response_json.get("eval_count", 0),
        finish_reason=finish_reason,
    )
