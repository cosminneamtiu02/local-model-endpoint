"""Tests covering create_app's production vs development branches."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_production_app_disables_openapi_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """In production mode (LIP_APP_ENV=production), every docs-tier route is disabled."""
    monkeypatch.setenv("LIP_APP_ENV", "production")
    # The autouse _reset_settings_cache fixture clears the lru_cache *before*
    # each test, so we don't need to call cache_clear() here — the cache is
    # guaranteed empty when the test body runs.
    from app.main import create_app

    app = create_app()
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
    # ``swagger_ui_oauth2_redirect_url`` is the fourth docs-tier knob FastAPI
    # exposes; without an explicit assertion the production-zero-docs-surface
    # invariant is mechanically pinned on three of four prongs and prose-only
    # on the fourth — exactly the asymmetric-coverage class that turns into a
    # regression incident the day a contributor refactors ``is_prod``.
    assert app.swagger_ui_oauth2_redirect_url is None


def test_development_app_exposes_openapi_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """In development mode (default), every docs-tier route is exposed."""
    monkeypatch.setenv("LIP_APP_ENV", "development")
    from app.main import create_app

    app = create_app()
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"
    # Symmetric with the production-side assertion — the FastAPI default for
    # this URL is ``/docs/oauth2-redirect`` when docs_url is set, so a future
    # constructor refactor that drops the prong silently in dev surfaces here.
    assert app.swagger_ui_oauth2_redirect_url == "/docs/oauth2-redirect"


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
    # ``getattr(m.cls, "__name__", repr(m.cls))`` — Starlette types
    # ``Middleware.cls`` as ``_MiddlewareFactory[P]`` (a Callable alias),
    # not ``type[...]``, so ``m.cls.__name__`` fails pyright strict.
    # The runtime value IS the actual middleware class so the access
    # works; the ``getattr`` fallback satisfies the static type without
    # losing the assertion-message affordance.
    assert app.user_middleware[-1].cls is RequestIdMiddleware, (
        "RequestIdMiddleware must be last-added (outermost) so request_id "
        f"contextvar binding wraps every nested middleware; got user_middleware="
        f"{[getattr(m.cls, '__name__', repr(m.cls)) for m in app.user_middleware]!r}"
    )


def test_lifespan_passes_get_settings_to_lifespan_resources() -> None:
    """``app.main.lifespan`` must call ``lifespan_resources(get_settings())``.

    ``lifespan_resources`` accepts a ``Settings`` instance directly so
    test fixtures can vary it under monkeypatch without going through the
    ``@lru_cache(maxsize=1)`` carve-out in ``app.api.deps.get_settings``.
    The docstring on ``lifespan_resources`` documents that production
    callers MUST pass ``get_settings()`` to preserve the cached-Settings
    invariant — bypassing it would construct two Settings instances per
    request lifetime.

    Without a mechanical pin, a future contributor could write
    ``lifespan_resources(Settings.model_validate({}))`` (or similar)
    inside ``lifespan`` and silently break the cached-Settings
    discipline; today's runtime would still appear to work, surfacing
    only as a tiny startup-latency increase no operator alarm catches.

    Mirrors the pattern of ``test_app_redirect_slashes_disabled_at_runtime``
    and ``test_request_id_middleware_is_outermost_user_middleware``: a
    source-inspection drift guard for an invariant whose only documentation
    today is prose.
    """
    import inspect

    from app.main import lifespan

    src = inspect.getsource(lifespan)
    # ``lifespan`` resolves settings via the ``get_settings()`` carve-out
    # factory at the top of its body and threads the resulting Settings
    # into ``lifespan_resources(settings)``. Pin both invariants:
    # (1) ``get_settings()`` is called inside ``lifespan`` (not a local
    #     ``Settings.model_validate(...)`` or hand-rolled construction), and
    # (2) ``lifespan_resources(settings)`` is the single feed shape (the
    #     factory's hand-pass contract).
    # Together these mechanically pin the cached-Settings invariant
    # documented on ``lifespan_resources`` — bypassing ``get_settings()``
    # would produce two Settings instances per request lifetime.
    assert "get_settings()" in src, (
        "app.main.lifespan must resolve Settings via the get_settings() "
        "carve-out factory — see lifespan_resources' docstring for the "
        "cached-Settings invariant."
    )
    assert "lifespan_resources(settings)" in src, (
        "app.main.lifespan must thread the get_settings()-resolved value "
        "into lifespan_resources(settings) — hand-passing Settings."
        "model_validate(...) bypasses the @lru_cache carve-out and "
        "produces two Settings instances per request lifetime."
    )
    # ``Settings.model_validate(`` and ``Settings(`` (constructor calls)
    # would both bypass the carve-out — flag either explicitly so the
    # drift-guard is precise about what's forbidden.
    assert "Settings.model_validate(" not in src, (
        "app.main.lifespan must NOT construct Settings via "
        "model_validate(...) — use the get_settings() carve-out factory."
    )


def test_create_app_invokes_audit_lip_env_typos(monkeypatch: pytest.MonkeyPatch) -> None:
    """``create_app`` MUST invoke ``audit_lip_env_typos`` exactly once.

    The audit's whole reason for existing (per ADR-014) is to surface
    typo'd ``LIP_*`` env vars that pydantic-settings silently ignores.
    The unit tests in ``tests/unit/api/test_deps.py`` drive the audit
    function directly; this integration test drives ``create_app`` so a
    regression that removes the call site at ``app/main.py`` turns the
    test red. Without this pin, the operator-discoverability contract
    relies entirely on prose; the call-site is invisible to the unit
    suite.

    Monkey-patches the audited symbol (``app.main.audit_lip_env_typos``,
    NOT the deps-module export) and counts invocations. Capturing logs
    via ``structlog.testing.capture_logs`` would not work here because
    ``create_app`` calls ``configure_logging`` which replaces structlog's
    processor chain mid-startup, dropping the test's capture.
    """
    monkeypatch.setenv("LIP_APP_ENV", "development")
    invocation_count = 0

    def _fake_audit() -> None:
        nonlocal invocation_count
        invocation_count += 1

    # Patch on ``app.main`` (the call site) rather than ``app.api.deps``
    # (the definition site) — Python imports bind a NAME at the time of
    # ``from X import Y``, so patching the source module after import
    # would leave ``main``'s already-bound reference untouched.
    import app.main

    monkeypatch.setattr(app.main, "audit_lip_env_typos", _fake_audit)
    app.main.create_app()
    assert invocation_count == 1
