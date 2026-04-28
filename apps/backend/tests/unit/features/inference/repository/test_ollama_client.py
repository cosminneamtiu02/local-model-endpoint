"""Unit tests for OllamaClient — the lifecycle-managed httpx wrapper.

Covers acceptance criteria from LIP-E003-F001 unit-test scenarios:
- construction with base_url
- DEFAULT_TIMEOUT shape
- async context manager support
- close() idempotency
- _request("GET", ...) and _request("POST", ..., json=...) plumbing
- _request privacy (single underscore — not part of public API surface)
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.features.inference.repository.ollama_client import (
    DEFAULT_TIMEOUT,
    OllamaClient,
)


def test_default_timeout_has_5s_connect_600s_read_unbounded_write_pool() -> None:
    """``DEFAULT_TIMEOUT`` is the v1 backstop until LIP-E004-F003 lands.

    Connect is 5s (Ollama is local, so a stalled connect is a real failure).
    Read is 600s — generous enough not to interrupt long-running thinking-mode
    inference under Gemma 4, but bounded so a hung daemon does not hold the
    single semaphore slot indefinitely (which would be a self-inflicted DoS).
    Write and pool stay unbounded — the request body is small relative to
    Ollama's response, and the connection pool is single-instance per
    lifespan.
    """
    assert DEFAULT_TIMEOUT.connect == 5.0
    assert DEFAULT_TIMEOUT.read == 600.0
    assert DEFAULT_TIMEOUT.write is None
    assert DEFAULT_TIMEOUT.pool is None


async def test_constructor_sets_base_url_on_internal_httpx_client() -> None:
    client = OllamaClient(base_url="http://localhost:11434")
    try:
        assert str(client._client.base_url) == "http://localhost:11434"
    finally:
        await client.close()


async def test_constructor_uses_default_timeout_when_none_supplied() -> None:
    client = OllamaClient(base_url="http://localhost:11434")
    try:
        assert client._client.timeout == DEFAULT_TIMEOUT
        # also verify the spec scenario directly so this test does
        # not depend on test_default_timeout_* having run first
        assert client._client.timeout.connect == 5.0
        assert client._client.timeout.read == 600.0
    finally:
        await client.close()


async def test_constructor_accepts_custom_timeout_override() -> None:
    custom = httpx.Timeout(connect=2.0, read=1.0, write=1.0, pool=1.0)
    client = OllamaClient(base_url="http://localhost:11434", timeout=custom)
    try:
        assert client._client.timeout == custom
    finally:
        await client.close()


async def test_async_context_manager_returns_self_and_closes_on_exit() -> None:
    async with OllamaClient(base_url="http://localhost:11434") as client:
        assert isinstance(client, OllamaClient)
        assert client._client.is_closed is False

    assert client._client.is_closed is True


async def test_async_context_manager_closes_on_exception_in_body() -> None:
    captured: OllamaClient | None = None
    with pytest.raises(RuntimeError, match="boom"):
        async with OllamaClient(base_url="http://localhost:11434") as client:
            captured = client
            raise RuntimeError("boom")

    assert captured is not None
    assert captured._client.is_closed is True


async def test_close_is_idempotent() -> None:
    client = OllamaClient(base_url="http://localhost:11434")
    await client.close()
    await client.close()  # second call must not raise
    assert client._client.is_closed is True


async def test_request_get_forwards_to_httpx_with_no_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, json={"models": []})

    transport = httpx.MockTransport(handler)
    async with OllamaClient(base_url="http://localhost:11434", transport=transport) as client:
        response = await client._request("GET", "/api/tags")

    assert response.status_code == 200
    assert response.json() == {"models": []}
    assert captured["method"] == "GET"
    assert captured["url"] == "http://localhost:11434/api/tags"
    assert captured["body"] == b""


async def test_request_post_sends_json_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    payload = {"model": "x", "messages": [{"role": "user", "content": "hi"}]}
    async with OllamaClient(base_url="http://localhost:11434", transport=transport) as client:
        response = await client._request("POST", "/api/chat", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured["method"] == "POST"
    assert captured["content_type"] == "application/json"

    body = captured["body"]
    assert isinstance(body, bytes | bytearray)
    assert json.loads(body) == payload


def test_request_method_is_private_not_in_public_api_surface() -> None:
    """The low-level helper is single-underscore, not part of the public class API."""
    public_attrs = [name for name in dir(OllamaClient) if not name.startswith("_")]
    assert "request" not in public_attrs
    # The single-underscore method exists but is by-convention internal
    assert hasattr(OllamaClient, "_request")
    # Public surface is: close + async context manager dunders only
    assert "close" in public_attrs


async def test_request_propagates_connect_error_via_mock_transport() -> None:
    """OllamaClient._request surfaces httpx.ConnectError to callers (deterministic).

    Unit-level coverage of AC11 (connection failures bubble up uncaught).
    Uses MockTransport so no real socket is opened — keeps the test
    hermetic and respects the unit-suite no-network rule. The integration
    counterpart in tests/integration/features/inference/test_lifecycle.py
    exercises a real loopback failure as a belt-and-braces check.
    """

    def _raises_connect(_request: httpx.Request) -> httpx.Response:
        msg = "simulated connect failure"
        raise httpx.ConnectError(msg)

    transport = httpx.MockTransport(_raises_connect)
    client = OllamaClient(base_url="http://example.invalid", transport=transport)
    try:
        with pytest.raises(httpx.ConnectError, match="simulated connect failure"):
            await client._request("GET", "/api/tags")
    finally:
        await client.close()
