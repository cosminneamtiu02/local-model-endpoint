"""Unit tests for OllamaClient — the lifecycle-managed httpx wrapper.

Covers acceptance criteria from LIP-E003-F001 unit-test scenarios:
- construction with base_url
- DEFAULT_TIMEOUT shape
- async context manager support
- close() idempotency
- _request("GET", ...) and _request("POST", ..., json=...) plumbing
- cancellation logging contract
"""

import asyncio
import json

import httpx
import pytest
from structlog.testing import capture_logs

from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams
from app.features.inference.repository.ollama_client import (
    DEFAULT_TIMEOUT,
    OllamaClient,
    _decode_ollama_json,
)


def test_default_timeout_constants_match_documented_v1_backstop() -> None:
    """``DEFAULT_TIMEOUT`` is the v1 backstop until LIP-E004-F003 lands.

    Connect is 5s (Ollama is local, so a stalled connect is a real failure).
    Read is 600s — generous enough not to interrupt long-running thinking-mode
    inference under Gemma 4, but bounded so a hung daemon does not hold the
    single semaphore slot indefinitely (which would be a self-inflicted DoS).
    Write stays unbounded — the request body is small relative to Ollama's
    response. Pool is 5s: with the LIP-E004-F001 semaphore set to 1
    in-flight, pool starvation should be unreachable today, but a finite
    ceiling converts a future regression (a sibling adapter call holding
    a slot) into a loud ``httpx.PoolTimeout`` rather than a silent hang.
    """
    assert DEFAULT_TIMEOUT.connect == 5.0
    assert DEFAULT_TIMEOUT.read == 600.0
    assert DEFAULT_TIMEOUT.write is None
    assert DEFAULT_TIMEOUT.pool == 5.0


async def test_constructor_sets_base_url_on_internal_httpx_client() -> None:
    client = OllamaClient(base_url="http://localhost:11434")
    try:
        assert str(client._client.base_url) == "http://localhost:11434"
    finally:
        await client.close()


async def test_constructor_uses_default_timeout_when_none_supplied() -> None:
    """Assert each timeout field rather than relying on a single equality
    of the whole ``httpx.Timeout`` value-object.

    Equality on httpx.Timeout is structural; a future httpx that adds a
    new field (or that breaks structural equality on Timeout) would let a
    real regression slip past a single ``client.timeout == DEFAULT_TIMEOUT``
    check. Field-by-field assertions stay specific to the four bounds we
    actually rely on.
    """
    client = OllamaClient(base_url="http://localhost:11434")
    try:
        assert client._client.timeout.connect == DEFAULT_TIMEOUT.connect
        assert client._client.timeout.read == DEFAULT_TIMEOUT.read
        assert client._client.timeout.write == DEFAULT_TIMEOUT.write
        assert client._client.timeout.pool == DEFAULT_TIMEOUT.pool
    finally:
        await client.close()


async def test_constructor_accepts_custom_timeout_override() -> None:
    """Field-by-field assertion mirrors the default-timeout test above."""
    custom = httpx.Timeout(connect=2.0, read=1.0, write=1.0, pool=1.0)
    client = OllamaClient(base_url="http://localhost:11434", timeout=custom)
    try:
        assert client._client.timeout.connect == custom.connect
        assert client._client.timeout.read == custom.read
        assert client._client.timeout.write == custom.write
        assert client._client.timeout.pool == custom.pool
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


# ── _decode_ollama_json malformed-frame branches ─────────────────────


def test_decode_ollama_json_rejects_non_json_content_type() -> None:
    """Non-JSON content-type surfaces as ValueError, not a confusing decode error.

    Builds the malformed-frame category the failure-mapping layer
    (LIP-E003-F003) translates uniformly. A regression that drops the
    content-type guard would let an HTML-error-page response through and
    fail with a less-actionable JSONDecodeError.
    """
    response = httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8"},
        content=b"<html>maintenance</html>",
    )
    with pytest.raises(ValueError, match="non-JSON content-type"):
        _decode_ollama_json(response)


def test_decode_ollama_json_rejects_malformed_json_body() -> None:
    """A malformed JSON body surfaces as ValueError chaining the decoder cause."""
    response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=b"{not json",
    )
    with pytest.raises(ValueError, match="non-JSON body under stream=False"):
        _decode_ollama_json(response)


def test_decode_ollama_json_rejects_non_object_payload() -> None:
    """A JSON array (or any non-object) at the top level is malformed for /api/chat."""
    response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json=[1, 2, 3],
    )
    with pytest.raises(ValueError, match="non-object JSON body"):
        _decode_ollama_json(response)


# ── _request input/state guards ──────────────────────────────────────


async def test_request_rejects_relative_path_with_value_error() -> None:
    """A relative ``path`` would silently RFC-3986-merge against ``base_url``.

    With ``base_url="http://localhost:11434"`` (no trailing slash), passing
    ``"api/chat"`` (no leading slash) replaces the last path segment instead
    of appending. Today's only call site (``chat`` -> ``"/api/chat"``) is
    fine, but the seam guards future siblings.
    """
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={}),
    )
    client = OllamaClient(base_url="http://example.invalid", transport=transport)
    try:
        with pytest.raises(ValueError, match="path must be absolute"):
            await client._request("GET", "api/tags")
    finally:
        await client.close()


async def test_request_rejects_use_after_close_with_runtime_error() -> None:
    """A leaked Depends-resolved reference arriving after lifespan teardown
    must surface a typed signal, not httpx's untyped internal RuntimeError.
    """
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={}),
    )
    client = OllamaClient(base_url="http://example.invalid", transport=transport)
    await client.close()
    with pytest.raises(RuntimeError, match="OllamaClient cannot be used after close"):
        await client._request("GET", "/api/tags")


# ── Cancellation contract ────────────────────────────────────────────


async def test_chat_cancellation_emits_cancelled_event_and_not_failed_event() -> None:
    """A cancelled chat() call emits ``ollama_call_cancelled`` exactly once and
    NEVER ``ollama_call_failed``.

    Drives a slow MockTransport handler so the chat() coroutine begins
    running and yields once on the slow path, then cancels the surrounding
    task. The Exception arm in ``OllamaClient.chat`` must bypass — only
    the narrow ``CancelledError`` arm (``ollama_call_cancelled``) should
    fire. Without this test, a future refactor that broadens the catch
    to ``BaseException`` would silently log the cancellation as a generic
    failure. (We do NOT promise the task is parked on the slow handler
    when ``cancel()`` runs — a single ``await asyncio.sleep(0)`` may not
    yield far enough on a contended session loop; what we DO assert is
    that whichever ``await`` point CancelledError lands at, the cancel
    arm fires the expected event_name.)
    """

    async def slow_handler(_request: httpx.Request) -> httpx.Response:
        # Park the request long enough for the surrounding task to be
        # cancelled before the response materializes. 10s is far above
        # the event-loop tick we wait for below.
        await asyncio.sleep(10)
        return httpx.Response(200, json={"message": {"content": "x"}, "done_reason": "stop"})

    transport = httpx.MockTransport(slow_handler)
    async with OllamaClient(base_url="http://ollama.test", transport=transport) as client:
        with capture_logs() as captured:
            task = asyncio.create_task(
                client.chat(
                    model_tag="gemma4:e2b",
                    messages=[Message(role="user", content="hi")],
                    params=ModelParams(),
                ),
            )
            # Yield control so the task starts and parks on the slow handler.
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        cancelled_events = [e for e in captured if e.get("event") == "ollama_call_cancelled"]
        failed_events = [e for e in captured if e.get("event") == "ollama_call_failed"]
        assert len(cancelled_events) == 1, captured
        assert failed_events == [], captured


# ── __aexit__ close-failure path ─────────────────────────────────────


async def test_aexit_propagates_close_error_when_body_did_not_raise() -> None:
    """``__aexit__`` propagates a close-time error when the body was clean.

    Body-error preservation rule (per ``OllamaClient.__aexit__`` docstring):
    when ``_exc is None`` (no body error to mask) and ``aclose()`` raises,
    let the close error surface — a silently-failed close is itself a bug.
    """
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    client = OllamaClient(base_url="http://ollama.test", transport=transport)

    async def _broken_close() -> None:
        msg = "simulated aclose failure"
        raise RuntimeError(msg)

    # type: ignore[method-assign]: monkey-patch close() to simulate an aclose
    # failure; the close-failure logging path needs the assignment.
    client.close = _broken_close  # type: ignore[method-assign]
    with capture_logs() as captured, pytest.raises(RuntimeError, match="simulated aclose failure"):
        async with client:
            pass

    failed = [e for e in captured if e.get("event") == "ollama_client_close_failed"]
    assert len(failed) == 1, captured
    assert failed[0]["exc_type"] == "RuntimeError"
    closed = [e for e in captured if e.get("event") == "ollama_client_closed"]
    assert closed == [], captured


async def test_aexit_suppresses_close_error_when_body_already_raised() -> None:
    """``__aexit__`` swallows close-time errors when the body raised first.

    The body's exception must reach the caller; the close-time error is
    logged but not re-raised so it cannot mask the body's E1 — the
    documented body-error preservation invariant.
    """
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    client = OllamaClient(base_url="http://ollama.test", transport=transport)

    async def _broken_close() -> None:
        msg = "secondary close failure"
        raise RuntimeError(msg)

    # type: ignore[method-assign]: monkey-patch close() to simulate a
    # close-time failure that must NOT mask the body's primary exception.
    client.close = _broken_close  # type: ignore[method-assign]
    with capture_logs() as captured, pytest.raises(ValueError, match="primary body error"):
        async with client:
            msg = "primary body error"
            raise ValueError(msg)

    failed = [e for e in captured if e.get("event") == "ollama_client_close_failed"]
    assert len(failed) == 1, captured
    closed = [e for e in captured if e.get("event") == "ollama_client_closed"]
    assert closed == [], captured


# ── _build_user_agent fallback ───────────────────────────────────────


async def test_build_user_agent_falls_back_when_package_metadata_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An editable install where importlib.metadata cannot resolve
    ``lip-backend`` should produce a ``lip-backend/unknown httpx/...`` UA
    AND emit ``ollama_user_agent_version_missing`` so the substitution
    is visible in logs.
    """
    from importlib import metadata as _metadata

    def _raise_not_found(_name: str) -> str:
        raise _metadata.PackageNotFoundError("lip-backend")

    monkeypatch.setattr(
        "app.features.inference.repository.ollama_client._metadata.version",
        _raise_not_found,
    )
    with capture_logs() as captured:
        client = OllamaClient(base_url="http://localhost:11434")
        try:
            assert client._user_agent.startswith("lip-backend/unknown httpx/")
        finally:
            await client.close()

    warnings = [e for e in captured if e.get("event") == "ollama_user_agent_version_missing"]
    assert len(warnings) == 1, captured
    assert warnings[0]["package_name"] == "lip-backend"
    assert warnings[0]["fallback_version"] == "unknown"
