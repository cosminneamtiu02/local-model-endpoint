"""Integration test fixtures — no database, no Testcontainers.

LIP holds no persistent state. Integration tests run the FastAPI app
in-process via httpx ASGITransport. No DB session overrides are needed
because no DB session exists.

httpx.ASGITransport does not fire the FastAPI lifespan — we drive it
explicitly via `app.router.lifespan_context(app)` so `app.state.context`
(typed AppState built by `lifespan_resources`) is populated before the
client issues its first request.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def app() -> AsyncIterator[FastAPI]:
    """Build a fresh app per-test (no shared singleton state)."""
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Async client driving the in-process FastAPI app via ASGITransport."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
