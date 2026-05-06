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


def test_app_redirect_slashes_disabled_at_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """``redirect_slashes=False`` is a wire-contract decision; pin it.

    FastAPI's default is ``redirect_slashes=True`` which 307-redirects a
    trailing-slash mismatch — but some httpx-based consumer SDKs drop POST
    bodies on 307. The ``main.py`` constructor passes ``redirect_slashes=
    False`` so a mismatch surfaces as a clean 404 problem+json (handled by
    the typed ``NotFoundError`` chain) instead. A future regression that
    flips the default back to True would emit no warning, no error, no
    log line — the regression surfaces only on a consumer's first 307
    retry. This assertion is the loud-fail backstop.
    """
    monkeypatch.setenv("LIP_APP_ENV", "development")
    from app.main import create_app

    app = create_app()
    assert app.router.redirect_slashes is False, (
        "redirect_slashes must be False — see app/main.py for the rationale; "
        "consumer SDKs that drop POST bodies on 307 would otherwise break silently."
    )


def test_request_id_middleware_is_outermost_user_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the middleware ordering invariant: ``RequestIdMiddleware`` is
    last-added (= outermost in Starlette's user-middleware stack).

    The middleware's docstring documents this requirement explicitly: any
    future middleware (compression, etc.) MUST be added BEFORE
    ``RequestIdMiddleware`` so it lands inside the wrapper. If a contributor
    adds ``application.add_middleware(...)`` AFTER the
    ``configure_middleware`` call, the new middleware ends up outside
    RequestIdMiddleware and silently breaks the ``request_id`` contextvar
    binding for any log lines emitted from the new middleware. This test
    fires at PR review time before the misordering hits production.
    """
    monkeypatch.setenv("LIP_APP_ENV", "development")
    from app.api.request_id_middleware import RequestIdMiddleware
    from app.main import create_app

    app = create_app()
    assert app.user_middleware, "expected at least one user middleware"
    # ``user_middleware[-1]`` is the LAST-ADDED entry — Starlette's LIFO
    # ordering makes that the OUTERMOST wrapper at request time.
    assert app.user_middleware[-1].cls is RequestIdMiddleware, (
        "RequestIdMiddleware must be last-added (outermost) so request_id "
        f"contextvar binding wraps every nested middleware; got user_middleware="
        f"{[m.cls.__name__ for m in app.user_middleware]!r}"
    )
