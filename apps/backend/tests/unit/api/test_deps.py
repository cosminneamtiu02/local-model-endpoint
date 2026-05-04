"""Unit tests for FastAPI dependency factories in app/api/deps.py.

The defensive ``isinstance(state, AppState)`` guard inside
``get_app_state`` was filed as a TDD gap by lane-7 in round 7 — the
defensive raise existed without a failing test partner. These tests
exercise the misconfigured-app branches so a future refactor of
AppState construction cannot break the type-narrowing without a red bar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog
from fastapi import FastAPI

from app.api.app_state import AppState
from app.api.deps import get_app_state, get_ollama_client, get_settings
from app.exceptions import InternalError

if TYPE_CHECKING:
    from fastapi import Request


def _request_for(app: FastAPI) -> Request:
    """Build a minimal ``Request`` whose ``request.app`` is the given app.

    ``get_app_state`` only reads ``request.app.state.context``; everything
    else on the Request object is irrelevant. Building from the ASGI scope
    avoids depending on TestClient and keeps these tests pure-unit.
    """
    from starlette.requests import Request as _Request

    scope: dict[str, object] = {
        "type": "http",
        "app": app,
        "headers": [],
        "method": "GET",
        "path": "/",
        "query_string": b"",
    }
    return _Request(scope)  # pyright: ignore[reportArgumentType]  # minimal scope is intentional


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
    """A wrong-typed ``app.state.context`` (e.g. raw dict from a stale test
    fixture) must also surface as InternalError, not as an attribute error
    deep inside ``get_ollama_client``."""
    app = FastAPI()
    app.state.context = {"ollama_client": "not-actually-a-client"}
    request = _request_for(app)
    with pytest.raises(InternalError, match=InternalError.code):
        get_app_state(request)


def test_get_app_state_returns_lifespan_appstate_on_happy_path() -> None:
    """When ``app.state.context`` is a valid AppState, get_app_state returns it."""
    from app.features.inference import OllamaClient

    app = FastAPI()
    client = OllamaClient(base_url="http://127.0.0.1:11434")
    state = AppState(ollama_client=client)
    app.state.context = state
    request = _request_for(app)

    assert get_app_state(request) is state


def test_get_ollama_client_delegates_through_get_app_state() -> None:
    """``get_ollama_client`` is a thin reader on top of ``get_app_state`` —
    test it returns the same client identity that AppState carries."""
    from app.features.inference import OllamaClient

    app = FastAPI()
    client = OllamaClient(base_url="http://127.0.0.1:11434")
    app.state.context = AppState(ollama_client=client)
    request = _request_for(app)

    assert get_ollama_client(request) is client


def test_get_settings_warns_on_unknown_lip_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo'd ``LIP_*`` env var should surface as a structlog warning
    (CLAUDE.md "never add an env var without adding it to Settings"), since
    pydantic-settings 2.14 silently ignores extras at the env-source layer.
    """
    monkeypatch.setenv("LIP_BOGUS_TYPO_VAR", "x")
    get_settings.cache_clear()
    with structlog.testing.capture_logs() as captured:
        get_settings()
    get_settings.cache_clear()
    warnings = [entry for entry in captured if entry.get("event") == "unknown_lip_env_vars_ignored"]
    assert len(warnings) == 1
    assert "LIP_BOGUS_TYPO_VAR" in warnings[0]["env_vars"]


def test_get_settings_does_not_warn_when_all_env_vars_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: only declared env vars set → no audit warning fires."""
    monkeypatch.setenv("LIP_LOG_LEVEL", "warning")
    get_settings.cache_clear()
    with structlog.testing.capture_logs() as captured:
        get_settings()
    get_settings.cache_clear()
    assert not [entry for entry in captured if entry.get("event") == "unknown_lip_env_vars_ignored"]
