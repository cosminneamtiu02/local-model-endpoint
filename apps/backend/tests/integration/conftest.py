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
    """
    from app.main import app

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
