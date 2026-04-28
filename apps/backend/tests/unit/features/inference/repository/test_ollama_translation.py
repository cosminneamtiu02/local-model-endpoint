"""Unit tests for ollama_translation pure helpers (LIP-E003-F002).

These three module-level functions are the entire envelope-to-Ollama
translation surface. They are tested directly (no httpx, no async) so
that translation logic stays decoupled from the transport.

The single most fragile mapping is `max_tokens -> num_predict`: a
dedicated test guards against silent regression of that rename.
"""

import pytest

from app.features.inference.model.audio_content import AudioContent
from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams
from app.features.inference.model.ollama_chat_result import OllamaChatResult
from app.features.inference.model.text_content import TextContent
from app.features.inference.repository.ollama_translation import (
    _PARAM_RENAMES,
    build_chat_result,
    translate_message,
    translate_params,
)

# ── translate_message ───────────────────────────────────────────────


def test_translate_message_string_content_passes_through() -> None:
    msg = Message(role="user", content="hi")
    assert translate_message(msg) == {"role": "user", "content": "hi"}


def test_translate_message_concatenates_multiple_text_parts_with_double_newline() -> None:
    msg = Message(
        role="user",
        content=[TextContent(text="A"), TextContent(text="B")],
    )
    assert translate_message(msg) == {"role": "user", "content": "A\n\nB"}


def test_translate_message_emits_images_array_for_base64_image_content() -> None:
    msg = Message(
        role="user",
        content=[
            TextContent(text="describe"),
            ImageContent(base64="iV..."),
        ],
    )
    assert translate_message(msg) == {
        "role": "user",
        "content": "describe",
        "images": ["iV..."],
    }


def test_translate_message_preserves_image_order_in_images_array() -> None:
    msg = Message(
        role="user",
        content=[
            ImageContent(base64="aaa"),
            ImageContent(base64="bbb"),
        ],
    )
    out = translate_message(msg)
    assert out["images"] == ["aaa", "bbb"]


def test_translate_message_no_images_key_when_only_text_parts() -> None:
    msg = Message(role="user", content=[TextContent(text="hi")])
    out = translate_message(msg)
    assert "images" not in out


def test_translate_message_empty_content_when_only_images() -> None:
    msg = Message(role="user", content=[ImageContent(base64="aaa")])
    out = translate_message(msg)
    assert out["content"] == ""
    assert out["images"] == ["aaa"]


@pytest.mark.parametrize("role", ["user", "assistant", "system"])
def test_translate_message_passes_through_each_allowed_role(role: str) -> None:
    msg = Message.model_validate({"role": role, "content": "hello"})
    assert translate_message(msg)["role"] == role


def test_translate_message_url_only_image_raises_not_implemented() -> None:
    msg = Message(role="user", content=[ImageContent(url="https://x/cat.png")])
    with pytest.raises(NotImplementedError, match="base64"):
        translate_message(msg)


def test_translate_message_audio_content_raises_not_implemented() -> None:
    """F002 leaves AudioContent translation [UNRESOLVED] pending live-Ollama check."""
    msg = Message(role="user", content=[AudioContent(base64="aaa")])
    with pytest.raises(NotImplementedError, match="audio"):
        translate_message(msg)


# ── translate_params ────────────────────────────────────────────────


def test_translate_params_default_returns_empty_dict() -> None:
    assert translate_params(ModelParams()) == {}


def test_translate_params_includes_only_consumer_set_temperature() -> None:
    assert translate_params(ModelParams(temperature=0.0)) == {"temperature": 0.0}


def test_translate_params_renames_max_tokens_to_num_predict() -> None:
    """The single most fragile mapping — guard against silent regression."""
    assert translate_params(ModelParams(max_tokens=512)) == {"num_predict": 512}


def test_translate_params_does_not_emit_max_tokens_key() -> None:
    """Belt-and-braces: no caller should ever see Ollama receive 'max_tokens'."""
    out = translate_params(ModelParams(max_tokens=512))
    assert "max_tokens" not in out


def test_translate_params_emits_all_six_sampling_fields_with_max_tokens_renamed() -> None:
    out = translate_params(
        ModelParams(
            temperature=0.5,
            top_p=0.9,
            top_k=40,
            max_tokens=512,
            stop=["X"],
            seed=42,
        ),
    )
    assert out == {
        "temperature": 0.5,
        "top_p": 0.9,
        "top_k": 40,
        "num_predict": 512,
        "stop": ["X"],
        "seed": 42,
    }


def test_translate_params_strips_think_from_options() -> None:
    """`think` is handled separately as a top-level Ollama field, not in options."""
    assert translate_params(ModelParams(think=True)) == {}


def test_translate_params_strips_think_when_combined_with_sampling_field() -> None:
    out = translate_params(ModelParams(think=True, temperature=0.7))
    assert out == {"temperature": 0.7}
    assert "think" not in out


def test_translate_params_includes_seed_zero() -> None:
    """Boundary: `seed=0` is a legitimate deterministic-generation request.
    Guards against a regression that uses `if params.seed:` (falsy filter)."""
    assert translate_params(ModelParams(seed=0)) == {"seed": 0}


def test_translate_params_includes_empty_stop_list() -> None:
    """Boundary: an explicit empty stop-list is a legitimate "no stop tokens"
    request. Guards against a regression that uses `if params.stop:`."""
    assert translate_params(ModelParams(stop=[])) == {"stop": []}


def test_param_renames_dict_contains_only_max_tokens() -> None:
    """Lock the rename table down to a single mapping; new renames need spec updates."""
    assert _PARAM_RENAMES == {"max_tokens": "num_predict"}


# ── build_chat_result ───────────────────────────────────────────────


def test_build_chat_result_maps_all_four_fields_from_ollama_response() -> None:
    result = build_chat_result(
        {
            "message": {"content": "hello"},
            "prompt_eval_count": 10,
            "eval_count": 5,
            "done_reason": "stop",
        },
    )
    assert result == OllamaChatResult(
        content="hello",
        prompt_tokens=10,
        completion_tokens=5,
        finish_reason="stop",
    )


def test_build_chat_result_maps_done_reason_length() -> None:
    result = build_chat_result(
        {
            "message": {"content": "x"},
            "prompt_eval_count": 1,
            "eval_count": 1,
            "done_reason": "length",
        },
    )
    assert result.finish_reason == "length"


def test_build_chat_result_falls_back_to_stop_for_unrecognized_done_reason() -> None:
    """Ollama's 'unload' (and any other unknown value) maps to 'stop'."""
    result = build_chat_result(
        {
            "message": {"content": "x"},
            "prompt_eval_count": 0,
            "eval_count": 0,
            "done_reason": "unload",
        },
    )
    assert result.finish_reason == "stop"


def test_build_chat_result_falls_back_to_stop_when_done_reason_missing() -> None:
    result = build_chat_result(
        {
            "message": {"content": "x"},
            "prompt_eval_count": 0,
            "eval_count": 0,
        },
    )
    assert result.finish_reason == "stop"


def test_build_chat_result_handles_zero_token_counts() -> None:
    result = build_chat_result(
        {
            "message": {"content": "x"},
            "prompt_eval_count": 0,
            "eval_count": 0,
            "done_reason": "stop",
        },
    )
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0


def test_build_chat_result_defaults_token_counts_when_missing() -> None:
    """A defensive default — Ollama should always send these but we don't crash if not."""
    result = build_chat_result({"message": {"content": "x"}, "done_reason": "stop"})
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0


def test_build_chat_result_raises_key_error_on_missing_message() -> None:
    """F003 catches at a higher layer; F002 lets the failure surface."""
    with pytest.raises(KeyError):
        build_chat_result({})


def test_build_chat_result_raises_key_error_on_missing_message_content() -> None:
    with pytest.raises(KeyError):
        build_chat_result({"message": {}})


def test_build_chat_result_ignores_tool_calls_when_content_present() -> None:
    """Spec: tool_calls in the response are ignored; only message.content
    is read. Tools are out of v1 scope, but Gemma 4 can emit tool_calls
    in some configurations — content stays the source of truth either way.
    """
    result = build_chat_result(
        {
            "message": {
                "content": "answer",
                "tool_calls": [{"function": {"name": "lookup", "arguments": {}}}],
            },
            "prompt_eval_count": 4,
            "eval_count": 2,
            "done_reason": "stop",
        },
    )
    assert result.content == "answer"
    assert result.prompt_tokens == 4
    assert result.completion_tokens == 2
