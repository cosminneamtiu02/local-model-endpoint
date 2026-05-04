"""Unit tests for FastAPI dependency factories in app/api/deps.py.

The defensive ``isinstance(state, AppState)`` guard inside
``get_app_state`` exists without a TDD partner unless these tests run —
they exercise the misconfigured-app branches so a future refactor of
AppState construction cannot break the type-narrowing without a red bar.
"""

from __future__ import annotations

import pytest
import structlog
from fastapi import FastAPI
from starlette.requests import Request

from app.api.app_state import AppState
from app.api.deps import audit_lip_env_typos, get_app_state, get_ollama_client, get_settings
from app.exceptions import InternalError


def _request_for(app: FastAPI) -> Request:
    """Build a minimal ``Request`` whose ``request.app`` is the given app.

    ``get_app_state`` only reads ``request.app.state.context``; everything
    else on the Request object is irrelevant. Building from the ASGI scope
    avoids depending on TestClient and keeps these tests pure-unit.
    """
    scope: dict[str, object] = {
        "type": "http",
        "app": app,
        "headers": [],
        "method": "GET",
        "path": "/",
        "query_string": b"",
    }
    return Request(scope)  # pyright: ignore[reportArgumentType]  # minimal scope is intentional


def test_get_app_state_when_context_missing_raises_internal_error() -> None:
    """A misconfigured app (lifespan didn't run) must surface as InternalError.

    Without this branch, the route handler would AttributeError on
    ``request.app.state.context.ollama_client`` and ship a bare 500
    instead of the typed RFC 7807 problem+json envelope.
    """
    app = FastAPI()
    request = _request_for(app)
    # ``match=`` pins the typed code so a future second InternalError
    # raise-site in ``get_app_state`` cannot silently shadow this branch's
    # contract — the test asserts *which* invariant fired, not just that
    # ``InternalError`` was raised somewhere.
    with pytest.raises(InternalError, match=InternalError.code):
        get_app_state(request)


def test_get_app_state_when_context_wrong_type_raises_internal_error() -> None:
    """A wrong-typed ``app.state.context`` must surface as InternalError.

    e.g. a raw dict left over from a stale test fixture must NOT surface
    as an attribute error deep inside ``get_ollama_client``.
    """
    app = FastAPI()
    app.state.context = {"ollama_client": "not-actually-a-client"}
    request = _request_for(app)
    with pytest.raises(InternalError, match=InternalError.code):
        get_app_state(request)


async def test_get_app_state_returns_lifespan_appstate_on_happy_path() -> None:
    """When ``app.state.context`` is a valid AppState, get_app_state returns it.

    The ``async with`` wrapping is load-bearing: ``OllamaClient.__init__``
    eagerly constructs ``httpx.AsyncClient`` (a transport pool open until
    aclose). Sibling ollama-client tests pair construction with explicit
    teardown; without the context manager here, ``filterwarnings=["error"]``
    would flip a future httpx-version pool-leak warning into a session-killing
    failure.
    """
    from app.features.inference import OllamaClient

    app = FastAPI()
    async with OllamaClient(base_url="http://127.0.0.1:11434") as client:
        state = AppState(ollama_client=client)
        app.state.context = state
        request = _request_for(app)

        assert get_app_state(request) is state


async def test_get_ollama_client_delegates_through_get_app_state() -> None:
    """``get_ollama_client`` returns the same client identity that AppState carries.

    It is a thin reader on top of ``get_app_state``. Wrapped in
    ``async with`` for the same pool-leak reason as the sibling
    happy-path test above.
    """
    from app.features.inference import OllamaClient

    app = FastAPI()
    async with OllamaClient(base_url="http://127.0.0.1:11434") as client:
        app.state.context = AppState(ollama_client=client)
        request = _request_for(app)

        assert get_ollama_client(request) is client


def test_audit_lip_env_typos_warns_on_unknown_lip_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo'd ``LIP_*`` env var should surface as a structlog warning.

    CLAUDE.md "never add an env var without adding it to Settings"
    relies on this audit, since pydantic-settings 2.14 silently ignores
    extras at the env-source layer.
    """
    monkeypatch.setenv("LIP_BOGUS_TYPO_VAR", "x")
    with structlog.testing.capture_logs() as captured:
        audit_lip_env_typos()
    warnings = [entry for entry in captured if entry.get("event") == "unknown_lip_env_vars_ignored"]
    assert len(warnings) == 1
    assert "LIP_BOGUS_TYPO_VAR" in warnings[0]["env_vars"]


def test_audit_lip_env_typos_does_not_warn_when_all_env_vars_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: only declared env vars set → no audit warning fires."""
    monkeypatch.setenv("LIP_LOG_LEVEL", "warning")
    with structlog.testing.capture_logs() as captured:
        audit_lip_env_typos()
    assert not [entry for entry in captured if entry.get("event") == "unknown_lip_env_vars_ignored"]


def test_get_settings_construction_no_longer_emits_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``get_settings`` no longer side-effects on env-var typos.

    The audit is now a separate ``audit_lip_env_typos`` call, fired from
    ``create_app`` AFTER ``configure_logging``. ``get_settings`` itself
    must therefore stay log-silent — otherwise the orphaned warning would
    re-introduce the orphaned-non-JSON-line bug this split fixed.
    """
    monkeypatch.setenv("LIP_BOGUS_TYPO_VAR", "x")
    # No leading/trailing ``cache_clear()``: the autouse
    # ``_reset_settings_cache`` fixture in ``tests/conftest.py`` already
    # clears the cache before every test, so manual clears here would be
    # dead defensive code (matches the ``test_config.py`` convention).
    with structlog.testing.capture_logs() as captured:
        get_settings()
    assert captured == []
