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
    """Provide an httpx AsyncClient wired to the FastAPI app via ASGI transport."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
