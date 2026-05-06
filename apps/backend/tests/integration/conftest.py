"""Integration test fixtures — no database, no Testcontainers.

LIP holds no persistent state. Integration tests run the FastAPI app
in-process via httpx ASGITransport. No DB session overrides are needed
because no DB session exists.
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import AsyncClient

from tests._helpers import make_async_client


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """Provide an httpx AsyncClient wired to the FastAPI app via ASGI transport.

    Constructs the FastAPI app via ``create_app()`` per-test (rather than
    importing the module-singleton ``app.main.app``) so the autouse
    ``_clean_settings_env`` / ``_reset_settings_cache`` fixtures in the
    parent conftest.py actually take effect — a singleton built at module
    import time would freeze ``docs_url`` / ``openapi_url`` /
    ``log_level`` based on whatever Settings were live before the
    monkeypatch ran.

    Note on lifespan: see ``tests._helpers.make_async_client`` — ``ASGITransport``
    does NOT trigger FastAPI lifespan, so ``app.state.context`` is unset
    inside this fixture. Today no test using this fixture hits a route
    depending on ``app.state.context``; when LIP-E001-F002 lands the
    helper grows ``LifespanManager`` wrapping in one place.

    The catch-all-exception-handler invariant is asserted inside
    ``make_async_client`` so every consumer (this fixture + the direct
    ``_build_app()`` callers in tests/integration/test_exception_handler_chain.py)
    gets the contract enforcement uniformly.
    """
    from app.main import create_app

    async with make_async_client(create_app()) as c:
        yield c
