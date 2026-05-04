"""Shared test helpers — assertion shortcuts that would otherwise drift across files.

Imported by tests in both ``tests/unit/exceptions/`` and ``tests/integration/`` so
the canonical RFC 7807 wire-shape invariants (status, content-type, code,
content-language, optionally request_id correlation) are pinned in exactly one
place. Adding a new invariant (or relaxing an existing one) is a single edit
instead of a 17-callsite sweep.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI
    from httpx import Response
    from starlette.types import ASGIApp


def make_test_client(app: FastAPI) -> TestClient:
    """Sync FastAPI ``TestClient`` mirror of :func:`make_async_client`.

    ``raise_server_exceptions=False`` mirrors the production catch-all path:
    the user-level Exception handler returns the 500 response and the
    framework re-raises only for telemetry — the consumer always sees the
    handler's response. Single source of truth for the contract-tier client
    pattern (was repeated seven times across the contract suite).
    """
    return TestClient(app, raise_server_exceptions=False)


@asynccontextmanager
async def make_async_client(app: ASGIApp) -> AsyncIterator[AsyncClient]:
    """Yield an httpx AsyncClient wired to ``app`` via ASGI transport.

    Single source of truth for the integration-tier client construction
    pattern (was duplicated across ``tests/integration/conftest.py`` and
    ``tests/integration/test_problem_details.py``). ``raise_app_exceptions
    =False`` mirrors the production code path: under uvicorn the user-level
    Exception handler returns the 500 response and the framework re-raises
    only for telemetry — the consumer always sees the handler's response.

    Note on lifespan: ``ASGITransport`` does NOT trigger FastAPI's lifespan
    events (that's a documented httpx + starlette intersection). Tests that
    depend on ``app.state.context`` being populated by ``lifespan_resources``
    must wrap with ``LifespanManager`` (asgi-lifespan) or use
    ``fastapi.testclient.TestClient`` instead. Today no integration test
    needs lifespan because no route reads ``app.state.context`` — when the
    inference router lands (LIP-E001-F002), this helper grows the lifespan
    wrapping in one place.
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def assert_problem_json_envelope(
    response: Response,
    *,
    status: int,
    code: str,
    check_request_id_correlation: bool = False,
) -> dict[str, Any]:
    """Assert the canonical RFC 7807 envelope invariants on a response.

    Always-checked invariants:
      1. HTTP status matches.
      2. Content-Type is ``application/problem+json; charset=utf-8`` (the
         LIP-pinned form, not the bare ``application/problem+json`` RFC 7807
         §3 permits).
      3. Content-Language is ``en`` (LIP v1's i18n contract).
      4. Body carries the LIP-extension ``code`` matching the typed error.
      5. Body carries a ``request_id`` (correlation handle).

    Optional invariant (``check_request_id_correlation=True``):
      6. Body's ``request_id`` matches the ``X-Request-ID`` response header
         (correlation contract — middleware ↔ handler).

    Returns the parsed body so the call site can make code-specific
    follow-up assertions.
    """
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json; charset=utf-8"
    assert response.headers["content-language"] == "en"
    body = response.json()
    assert body["code"] == code
    assert "request_id" in body
    if check_request_id_correlation:
        assert body["request_id"] == response.headers["X-Request-ID"]
    return body
