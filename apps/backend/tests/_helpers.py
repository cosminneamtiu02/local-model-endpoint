"""Shared test helpers — assertion shortcuts that would otherwise drift across files.

Imported by tests in both ``tests/unit/exceptions/`` and ``tests/integration/`` so
the canonical RFC 7807 wire-shape invariants (status, content-type, code,
content-language, body.status, optionally request_id correlation) are pinned
in exactly one place. Adding a new invariant (or relaxing an existing one) is
a single edit instead of a multi-call-site sweep.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.schemas.wire_constants import REQUEST_ID_HEADER

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI
    from httpx import Response
    from starlette.types import ASGIApp


def make_test_client(app: FastAPI) -> TestClient:
    """Sync FastAPI ``TestClient`` mirror of :func:`make_async_client`.

    ``raise_server_exceptions=False`` mirrors the production catch-all path:
    the user-level Exception handler returns the 500 response and the
    framework re-raises only for telemetry — the consumer always sees the
    handler's response. Single source of truth for the contract-tier client
    pattern.
    """
    return TestClient(app, raise_server_exceptions=False)


@asynccontextmanager
async def make_async_client(app: ASGIApp) -> AsyncGenerator[AsyncClient]:
    """Yield an httpx AsyncClient wired to ``app`` via ASGI transport.

    Single source of truth for the integration-tier client construction
    pattern. ``raise_app_exceptions=False`` mirrors the production code
    path: under uvicorn the user-level Exception handler returns the 500
    response and the framework re-raises only for telemetry — the consumer
    always sees the handler's response.

    Note on lifespan: ``ASGITransport`` does NOT trigger FastAPI's lifespan
    events (that's a documented httpx + starlette intersection). Tests that
    depend on ``app.state.context`` being populated by ``lifespan_resources``
    must wrap with ``LifespanManager`` (asgi-lifespan) or use
    ``fastapi.testclient.TestClient`` instead. Today no integration test
    needs lifespan because no route reads ``app.state.context`` — when the
    inference router lands (LIP-E001-F002), this helper grows the lifespan
    wrapping in one place.
    """
    # ``raise_app_exceptions=False`` only matches production behavior if a
    # catch-all ``Exception`` handler is registered — otherwise an unhandled
    # exception silently disappears instead of surfacing as the operator's
    # 500 ProblemDetails. Assert at helper entry so every consumer (the
    # ``client`` fixture in tests/integration/conftest.py and the direct
    # ``_build_app()`` callers in tests/integration/test_exception_handler_chain.py)
    # gets the contract enforcement uniformly. ``getattr`` so non-FastAPI
    # ASGI apps without ``exception_handlers`` aren't broken (pure ASGI
    # apps used in middleware tests legitimately omit the registry).
    handlers = getattr(app, "exception_handlers", None)
    if handlers is not None:
        assert Exception in handlers, (
            "App must register a catch-all Exception handler — "
            "make_async_client's raise_app_exceptions=False contract relies on it."
        )
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
      6. Body's ``status`` field equals the wire ``response.status_code``
         (RFC 7807 §3.1 MUST). The handler is the source of truth for both,
         so a divergence pins a real handler bug.

    Optional invariant (``check_request_id_correlation=True``):
      7. Body's ``request_id`` matches the ``REQUEST_ID_HEADER`` response
         header value (correlation contract — middleware ↔ handler;
         see :data:`app.schemas.wire_constants.REQUEST_ID_HEADER`).

    Returns the parsed body so the call site can make code-specific
    follow-up assertions.
    """
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json; charset=utf-8"
    assert response.headers["content-language"] == "en"
    body = response.json()
    assert body["code"] == code
    assert "request_id" in body
    assert body["status"] == status
    if check_request_id_correlation:
        assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    return body
