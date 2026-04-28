"""Integration tests for OllamaClient.chat() (LIP-E003-F002).

Pattern: a `httpx.MockTransport` records the outgoing request body and
returns canned Ollama JSON. We never speak to a live Ollama. Same shape
as test_lifecycle.py's MockTransport round-trip; this file is the
typed-method counterpart that exercises the full chat round trip.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams
from app.features.inference.model.text_content import TextContent
from app.features.inference.repository.ollama_client import OllamaClient

if TYPE_CHECKING:
    from app.features.inference.model.ollama_chat_result import OllamaChatResult


def _ollama_ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "message": {"content": "hello"},
            "prompt_eval_count": 10,
            "eval_count": 5,
            "done_reason": "stop",
        },
    )


async def _send_and_capture(
    *,
    model_tag: str = "gemma4:e2b",
    messages: list[Message] | None = None,
    params: ModelParams | None = None,
    response: httpx.Response | None = None,
) -> tuple[dict[str, Any], httpx.Request, OllamaChatResult]:
    """Send a chat() call through MockTransport.

    Returns (parsed_request_body, raw_request, OllamaChatResult). Defaults
    are explicit `is None` checks rather than `or` so an empty list / a
    bare `ModelParams()` from the caller passes through verbatim.
    """
    captured: dict[str, httpx.Request] = {}
    effective_messages = messages if messages is not None else [Message(role="user", content="hi")]
    effective_params = params if params is not None else ModelParams()

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return response if response is not None else _ollama_ok_response()

    transport = httpx.MockTransport(handler)
    async with OllamaClient(base_url="http://ollama.test", transport=transport) as client:
        result = await client.chat(
            model_tag=model_tag,
            messages=effective_messages,
            params=effective_params,
        )

    request = captured["request"]
    parsed: dict[str, Any] = json.loads(request.content) if request.content else {}
    return parsed, request, result


# ── Outbound request shape ──────────────────────────────────────────


async def test_chat_simple_text_produces_minimal_ollama_chat_body() -> None:
    body, request, _ = await _send_and_capture(
        messages=[Message(role="user", content="hi")],
        params=ModelParams(temperature=0.0),
    )
    assert request.method == "POST"
    assert request.url.path == "/api/chat"
    assert body == {
        "model": "gemma4:e2b",
        "messages": [{"role": "user", "content": "hi"}],
        "options": {"temperature": 0.0},
        "stream": False,
    }


async def test_chat_multimodal_image_message_produces_images_array() -> None:
    body, _, _ = await _send_and_capture(
        messages=[
            Message(
                role="user",
                content=[
                    TextContent(text="describe"),
                    ImageContent(base64="iV..."),
                ],
            ),
        ],
    )
    assert body["messages"] == [
        {"role": "user", "content": "describe", "images": ["iV..."]},
    ]


async def test_chat_renames_max_tokens_to_num_predict_in_options() -> None:
    """Single regression test for the rename — silent regression breaks production."""
    body, _, _ = await _send_and_capture(params=ModelParams(max_tokens=512))
    assert body["options"] == {"num_predict": 512}
    assert "max_tokens" not in body["options"]


async def test_chat_places_think_inside_options_per_f002_spec() -> None:
    """LIP-E003-F002 [RESOLVED]: ``think`` rides inside ``options`` (locked placement)."""
    body, _, _ = await _send_and_capture(params=ModelParams(think=True))
    assert body["options"]["think"] is True
    # think must NOT appear at the top level
    assert "think" not in body


async def test_chat_includes_think_false_in_options_when_explicitly_set() -> None:
    """Symmetric with every other ModelParams field: explicitly-set values are
    faithfully transmitted via ``model_dump(exclude_unset=True)``. ``think=False``
    set by the consumer rides as ``options.think=False`` (overrides any model-side
    thinking-mode default at Ollama)."""
    body, _, _ = await _send_and_capture(params=ModelParams(think=False))
    assert body["options"]["think"] is False
    assert "think" not in body  # never top-level


async def test_chat_omits_think_when_unset() -> None:
    body, _, _ = await _send_and_capture(params=ModelParams())
    assert "think" not in body
    assert "options" not in body  # bare ModelParams produces no options key at all


async def test_chat_omits_options_when_no_consumer_set_params() -> None:
    body, _, _ = await _send_and_capture(params=ModelParams())
    assert "options" not in body


async def test_chat_emits_body_keys_in_spec_order() -> None:
    """Wire-body key order mirrors the spec acceptance-criterion example
    (model, messages, options, stream) so JSON dumps are reviewable
    side-by-side with graphs/LIP/LIP-E003-F002.md.
    """
    body, _, _ = await _send_and_capture(params=ModelParams(temperature=0.0))
    assert list(body.keys()) == ["model", "messages", "options", "stream"]


async def test_chat_always_sets_stream_false() -> None:
    """All five param shapes must produce stream:false — non-negotiable invariant."""
    shapes = [
        ModelParams(),
        ModelParams(temperature=0.5),
        ModelParams(max_tokens=100),
        ModelParams(think=True),
        ModelParams(temperature=0.5, top_p=0.9, top_k=40, seed=42),
    ]
    for params in shapes:
        body, _, _ = await _send_and_capture(params=params)
        assert body.get("stream") is False, f"stream should be false for {params!r}"


async def test_chat_never_sends_tools_keep_alive_or_format_keys() -> None:
    """Forbidden fields invariant across the same five shapes."""
    shapes = [
        ModelParams(),
        ModelParams(temperature=0.5),
        ModelParams(max_tokens=100),
        ModelParams(think=True),
        ModelParams(temperature=0.5, top_p=0.9, top_k=40, seed=42),
    ]
    forbidden = {"tools", "keep_alive", "format"}
    for params in shapes:
        body, _, _ = await _send_and_capture(params=params)
        assert forbidden.isdisjoint(body.keys()), (
            f"forbidden fields leaked for {params!r}: {set(body) & forbidden}"
        )


# ── Inbound response translation ────────────────────────────────────


async def test_chat_returns_ollama_chat_result_with_translated_fields() -> None:
    _, _, result = await _send_and_capture()
    assert result.content == "hello"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.finish_reason == "stop"


async def test_chat_ignores_tool_calls_in_response_and_uses_content() -> None:
    """Spec: tool_calls are ignored at the adapter; content is the canonical answer."""
    response = httpx.Response(
        200,
        json={
            "message": {
                "content": "answer",
                "tool_calls": [{"function": {"name": "lookup", "arguments": {}}}],
            },
            "prompt_eval_count": 4,
            "eval_count": 2,
            "done_reason": "stop",
        },
    )
    _, _, result = await _send_and_capture(response=response)
    assert result.content == "answer"


# ── Failure propagation ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "status_code",
    [
        pytest.param(400, id="bad-request"),
        pytest.param(404, id="model-not-found"),
        pytest.param(500, id="internal-server-error"),
        pytest.param(503, id="service-unavailable"),
    ],
)
async def test_chat_propagates_http_status_error_for_every_non_2xx(
    status_code: int,
) -> None:
    """raise_for_status() turns any non-2xx into HTTPStatusError; F003 maps later."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "x"})

    transport = httpx.MockTransport(handler)
    async with OllamaClient(base_url="http://ollama.test", transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.chat(
                model_tag="gemma4:e2b",
                messages=[Message(role="user", content="hi")],
                params=ModelParams(),
            )


async def test_chat_propagates_read_timeout_uncaught() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        msg = "simulated read timeout"
        raise httpx.ReadTimeout(msg, request=request)

    transport = httpx.MockTransport(handler)
    async with OllamaClient(base_url="http://ollama.test", transport=transport) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.chat(
                model_tag="gemma4:e2b",
                messages=[Message(role="user", content="hi")],
                params=ModelParams(),
            )


async def test_chat_propagates_connect_timeout_uncaught() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        msg = "simulated connect timeout"
        raise httpx.ConnectTimeout(msg, request=request)

    transport = httpx.MockTransport(handler)
    async with OllamaClient(base_url="http://ollama.test", transport=transport) as client:
        with pytest.raises(httpx.ConnectTimeout):
            await client.chat(
                model_tag="gemma4:e2b",
                messages=[Message(role="user", content="hi")],
                params=ModelParams(),
            )
