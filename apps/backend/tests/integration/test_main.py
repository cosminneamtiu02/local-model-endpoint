"""Tests covering create_app's production vs development branches."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_production_app_disables_openapi_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """In production mode (LIP_APP_ENV=production), /docs, /redoc, /openapi.json are disabled."""
    monkeypatch.setenv("LIP_APP_ENV", "production")
    # The autouse _reset_settings_cache fixture clears the lru_cache *before*
    # each test, so we don't need to call cache_clear() here — the cache is
    # guaranteed empty when the test body runs.
    from app.main import create_app

    app = create_app()
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_development_app_exposes_openapi_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """In development mode (default), /docs, /redoc, /openapi.json are exposed."""
    monkeypatch.setenv("LIP_APP_ENV", "development")
    from app.main import create_app

    app = create_app()
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"
