"""Integration test fixtures — no database, no Testcontainers.

LIP holds no persistent state. Integration tests run the FastAPI app
in-process via httpx ASGITransport. No DB session overrides are needed
because no DB session exists.
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """Provide an httpx AsyncClient wired to the FastAPI app via ASGI transport.

    ``raise_app_exceptions=False`` mirrors the production code path: under
    uvicorn, the user-level Exception handler returns the 500 response and
    the framework re-raises only for telemetry — the consumer always sees
    the handler's response. Without this flag, ASGITransport re-raises into
    the test, which is a test-only artifact, not a real-traffic behavior.

    The contract above only holds because the production app registers a
    catch-all ``Exception`` handler. Assert that explicitly so a future
    regression that drops or narrows the catch-all surfaces as a clear
    fixture-time AssertionError instead of as silently divergent
    test-vs-prod behavior.
    """
    from app.main import app

    assert Exception in app.exception_handlers, (
        "Production app must register a catch-all Exception handler — "
        "the conftest's raise_app_exceptions=False contract relies on it."
    )

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
