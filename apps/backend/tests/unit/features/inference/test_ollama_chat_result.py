"""Unit tests for OllamaChatResult (LIP-E003-F002).

The intermediate value-object that `OllamaClient.chat()` returns. The
orchestrator (LIP-E001-F002) composes the public `InferenceResponse`
from this plus its own metadata; F002 only owns the four fields it can
itself observe (content, prompt/completion tokens, finish reason).
"""

import pytest
from pydantic import ValidationError

from app.features.inference.model.ollama_chat_result import OllamaChatResult


def _valid_kwargs() -> dict[str, object]:
    return {
        "content": "hello",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "finish_reason": "stop",
    }


def test_ollama_chat_result_constructs_with_all_four_fields() -> None:
    result = OllamaChatResult.model_validate(_valid_kwargs())
    assert result.content == "hello"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.finish_reason == "stop"


def test_ollama_chat_result_is_frozen() -> None:
    result = OllamaChatResult(
        content="x",
        prompt_tokens=1,
        completion_tokens=1,
        finish_reason="stop",
    )
    with pytest.raises(ValidationError, match="frozen"):
        # Intentional frozen-violation to assert the runtime guard fires.
        # Pyright flags the assignment because frozen=True makes the
        # field effectively read-only at the type level.
        result.content = "y"  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize(
    "finish_reason",
    ["stop", "length", "timeout"],
)
def test_ollama_chat_result_accepts_each_allowed_finish_reason(finish_reason: str) -> None:
    kwargs = _valid_kwargs()
    kwargs["finish_reason"] = finish_reason
    result = OllamaChatResult.model_validate(kwargs)
    assert result.finish_reason == finish_reason


def test_ollama_chat_result_rejects_invalid_finish_reason() -> None:
    kwargs = _valid_kwargs()
    kwargs["finish_reason"] = "bad"
    with pytest.raises(ValidationError, match="finish_reason"):
        OllamaChatResult.model_validate(kwargs)


@pytest.mark.parametrize(
    "field",
    ["content", "prompt_tokens", "completion_tokens", "finish_reason"],
)
def test_ollama_chat_result_requires_every_field(field: str) -> None:
    kwargs = _valid_kwargs()
    del kwargs[field]
    with pytest.raises(ValidationError, match=field):
        OllamaChatResult.model_validate(kwargs)


def test_ollama_chat_result_rejects_unknown_field() -> None:
    kwargs = _valid_kwargs()
    kwargs["bogus"] = "x"
    with pytest.raises(ValidationError, match="extra"):
        OllamaChatResult.model_validate(kwargs)


def test_ollama_chat_result_accepts_zero_token_counts() -> None:
    result = OllamaChatResult(
        content="",
        prompt_tokens=0,
        completion_tokens=0,
        finish_reason="stop",
    )
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0


@pytest.mark.parametrize("field", ["prompt_tokens", "completion_tokens"])
def test_ollama_chat_result_rejects_negative_token_counts(field: str) -> None:
    """Symmetry with `ResponseMetadata` — negative token counts from a
    misbehaving Ollama daemon must not propagate up unchecked."""
    kwargs = _valid_kwargs()
    kwargs[field] = -1
    with pytest.raises(ValidationError, match=field):
        OllamaChatResult.model_validate(kwargs)
