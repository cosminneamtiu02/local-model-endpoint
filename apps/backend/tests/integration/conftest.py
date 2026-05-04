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

    The contract above only holds because the production app registers a
    catch-all ``Exception`` handler. Assert that explicitly so a future
    regression that drops or narrows the catch-all surfaces as a clear
    fixture-time AssertionError instead of as silently divergent
    test-vs-prod behavior.
    """
    from app.main import create_app

    app = create_app()
    assert Exception in app.exception_handlers, (
        "Production app must register a catch-all Exception handler — "
        "the conftest's raise_app_exceptions=False contract relies on it."
    )

    async with make_async_client(app) as c:
        yield c
