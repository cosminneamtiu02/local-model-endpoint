"""Top-level test fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Reset get_settings's lru_cache around every test."""
    from app.api.deps import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_structlog_contextvars() -> Iterator[None]:
    """Clear structlog contextvars between tests.

    structlog.reset_defaults() (used elsewhere) resets configuration only,
    not the per-task contextvars dict. Without this clear, a test that binds
    request_id / error_code via structlog.contextvars.bind_contextvars
    leaves stale keys for the next test in the same worker. Promoted to
    project-wide so non-logging tests inherit the isolation.
    """
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()
