"""Integration tests for OllamaClient lifecycle and FastAPI wiring.

Covers LIP-E003-F001 integration scenarios:
- MockTransport + OllamaClient round-trip (validates the _request plumbing
  + the MockTransport injection pattern other features will reuse).
- Lifespan-managed singleton: exactly one OllamaClient is constructed
  at app startup and exactly one close() at shutdown.
- app.state.ollama_client identity survives across multiple requests.
- AC8: shutdown calls close() from finally even when the app body raises.
- AC11: connection failures raise httpx.ConnectError uncaught from _request.
"""

from __future__ import annotations

from typing import Annotated

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.deps import get_ollama_client
from app.features.inference.repository.ollama_client import OllamaClient


async def test_mock_transport_allows_full_request_round_trip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with OllamaClient(base_url="http://localhost:11434", transport=transport) as client:
        response = await client._request("GET", "/api/tags")

    assert response.status_code == 200
    assert response.json() == {"models": []}


def test_lifespan_constructs_and_closes_client_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.features.inference.repository import ollama_client as oc_mod
    from app.main import create_app

    init_count = 0
    close_count = 0
    original_init = oc_mod.OllamaClient.__init__
    original_close = oc_mod.OllamaClient.close

    def counting_init(
        self: OllamaClient,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal init_count
        init_count += 1
        original_init(self, *args, **kwargs)

    async def counting_close(self: OllamaClient) -> None:
        nonlocal close_count
        close_count += 1
        await original_close(self)

    monkeypatch.setattr(oc_mod.OllamaClient, "__init__", counting_init)
    monkeypatch.setattr(oc_mod.OllamaClient, "close", counting_close)

    app = create_app()
    with TestClient(app):
        # entering and exiting the context manager triggers lifespan
        # startup + shutdown
        pass

    assert init_count == 1
    assert close_count == 1


def test_app_state_client_survives_across_requests() -> None:
    from app.main import create_app

    app = create_app()

    @app.get("/_test/ollama_client_id")
    async def echo_client_id(
        client: Annotated[OllamaClient, Depends(get_ollama_client)],
    ) -> dict[str, int]:
        return {"id": id(client)}

    with TestClient(app) as test_client:
        r1 = test_client.get("/_test/ollama_client_id")
        r2 = test_client.get("/_test/ollama_client_id")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


async def test_lifespan_close_runs_even_when_yield_body_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8: lifespan finally: must close the client even if the app body raises.

    Drives the lifespan context manager directly so we can inject an
    exception at the yield point (the "app body" in the spec's wording).
    The TestClient route-handler path can't reproduce this — FastAPI
    catches request-handler exceptions before they reach the lifespan
    generator; we need to raise into the async-with body itself.
    """
    from app.features.inference.repository import ollama_client as oc_mod
    from app.main import create_app, lifespan

    close_count = 0
    original_close = oc_mod.OllamaClient.close

    async def counting_close(self: OllamaClient) -> None:
        nonlocal close_count
        close_count += 1
        await original_close(self)

    monkeypatch.setattr(oc_mod.OllamaClient, "close", counting_close)

    app = create_app()
    boom = "simulated app-body failure"
    with pytest.raises(RuntimeError, match=boom):
        async with lifespan(app):
            raise RuntimeError(boom)

    assert close_count == 1


async def test_request_propagates_httpx_connect_error_uncaught() -> None:
    """AC11: connection failures raise httpx.ConnectError; F001 doesn't catch.

    Mapping httpx exceptions to typed DomainError is LIP-E003-F003's job.
    """
    # 127.0.0.1 with an unbound port is the canonical "guaranteed refused"
    # endpoint — it short-circuits without leaving the loopback stack.
    async with OllamaClient(base_url="http://127.0.0.1:1") as client:
        with pytest.raises(httpx.ConnectError):
            await client._request("GET", "/api/tags")
