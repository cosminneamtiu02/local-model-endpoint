"""Contract-tier conftest — per-test ``create_app()`` fixture.

Mirrors the integration tier's hermeticity policy (see
``tests/integration/conftest.py``): each test gets its own FastAPI
instance built from the current Settings env, rather than the module-
singleton ``app.main:app`` which freezes Settings at the first import
time (before any monkeypatch fixture takes effect). The autouse
``_clean_settings_env`` fixture in the root conftest then guarantees the
construction sees a scrubbed environment.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests._helpers import make_test_client


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Yield a sync ``TestClient`` over a freshly-built FastAPI instance."""
    application = create_app()
    with make_test_client(application) as test_client:
        yield test_client
