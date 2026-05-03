"""Shared FastAPI dependencies."""

from functools import lru_cache

from fastapi import Request

from app.api.app_state import AppState
from app.core.config import Settings
from app.exceptions import InternalError
from app.features.inference import OllamaClient


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    # ``Settings.model_validate({})`` runs the BaseSettings env / .env load
    # path the same way ``Settings()`` does, but goes through Pydantic's
    # typed ``model_validate`` entry point so pyright doesn't see a
    # dynamic-init false-positive. Avoids the ``# pyright: ignore`` escape
    # hatch and keeps the construction site contract-clean.
    return Settings.model_validate({})


def get_app_state(request: Request) -> AppState:
    """Return the lifespan-managed AppState attached at startup.

    A typed isinstance guard catches the misconfigured-app case (lifespan
    didn't run, or ``app.state.context`` was never set) and raises a typed
    InternalError so the response stays RFC 7807 problem+json instead of
    surfacing as a bare AttributeError 500.
    """
    state: object = getattr(request.app.state, "context", None)
    if not isinstance(state, AppState):
        # ruff's RSE102 prefers ``raise X`` over ``raise X()`` for
        # parameterless exception classes — Python auto-instantiates and
        # the no-parens form makes the intent obvious.
        raise InternalError
    return state


def get_ollama_client(request: Request) -> OllamaClient:
    """Return the lifespan-managed OllamaClient.

    Reads off the typed AppState that lifespan_resources stores on
    `app.state.context` so feature handlers don't need cast() and stay
    pyright-strict.
    """
    return get_app_state(request).ollama_client
