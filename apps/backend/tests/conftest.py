"""Top-level test fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Reset get_settings's lru_cache around every test.

    Session-scoped event loop + lru_cache singletons would otherwise leak
    Settings state across tests. The clear runs *before* yield so a test
    that sets ``LIP_APP_ENV=production`` and then constructs the app
    sees a fresh Settings — without it, the cache holds whatever the
    previous test left behind. The post-yield clear also runs so the
    *next* test's pre-yield clear is symmetric (and so a test that does
    not import ``get_settings`` still has clean state on exit).

    Note: ``asyncio_default_fixture_loop_scope = "session"`` in
    pyproject.toml means async fixtures keep their event loop across
    tests, so any new session-scoped async fixture that captures
    mutable state must implement its own per-test reset hook (or be
    function-scoped); ``_reset_settings_cache`` only handles
    ``get_settings`` specifically.
    """
    from app.api.deps import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
