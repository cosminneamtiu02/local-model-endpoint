"""Contract-tier conftest — per-test ``create_app()`` fixture.

Mirrors the integration tier's hermeticity policy (see
``tests/integration/conftest.py``): each test gets its own FastAPI
instance built from the current Settings env, rather than the module-
singleton ``app.main:app`` which freezes Settings at the first import
time (before any monkeypatch fixture takes effect). The autouse
``_clean_settings_env`` fixture in the root conftest then guarantees the
construction sees a scrubbed environment.

FORWARD (LIP-E001-F002 + Schemathesis fuzz suite): when the inference
router lands and Schemathesis is added per CLAUDE.md ADR-011's
schemathesis FORWARD note, prefer
``schemathesis.openapi.from_uri("http://test/openapi.json",
session=client)`` (over ``schemathesis.from_asgi(app=app, ...)``) so
the fuzz path exercises the SAME wire route the existing OpenAPI
canary fetches from. ``from_asgi`` would bypass the ``/openapi.json``
publication entirely; if a future regression broke the route (e.g.
an ``openapi_url=None`` flip in non-prod), the canary would fire but
the fuzz suite would silently report "no operations to fuzz". Wiring
fuzz through the same wire path keeps both contracts in lockstep.
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
