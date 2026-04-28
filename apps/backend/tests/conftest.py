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

    This is a stop-gap until E004 lands the semaphore (which will need
    similar hygiene per LIP-E004-F001 spec).
    """
    from app.api.deps import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
