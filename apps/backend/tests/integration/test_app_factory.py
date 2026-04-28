"""Tests covering create_app's production vs development branches."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_production_app_disables_openapi_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """In production mode (APP_ENV=production), /docs, /redoc, /openapi.json are disabled."""
    monkeypatch.setenv("APP_ENV", "production")
    # Reset the lru_cache so create_app sees the new env.
    from app.api.deps import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None

    # Cleanup the cache so other tests don't see "production".
    get_settings.cache_clear()


def test_development_app_exposes_openapi_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """In development mode (default), /docs, /redoc, /openapi.json are exposed."""
    monkeypatch.setenv("APP_ENV", "development")
    from app.api.deps import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"

    get_settings.cache_clear()
