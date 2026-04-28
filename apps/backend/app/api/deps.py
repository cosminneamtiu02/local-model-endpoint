"""Shared FastAPI dependencies."""

from functools import lru_cache

from fastapi import Request

from app.api.state import AppState
from app.core.config import Settings
from app.features.inference.repository import OllamaClient


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    # pydantic-settings loads required fields from env / .env at construction time;
    # pyright doesn't see the BaseSettings dynamic init so we suppress the false call-issue.
    return Settings()  # pyright: ignore[reportCallIssue]


def get_app_state(request: Request) -> AppState:
    """Return the lifespan-managed AppState attached at startup."""
    state: AppState = request.app.state.context
    return state


def get_ollama_client(request: Request) -> OllamaClient:
    """Return the lifespan-managed OllamaClient.

    Reads off the typed AppState that lifespan_resources stores on
    `app.state.context` so feature handlers don't need cast() and stay
    pyright-strict.
    """
    return get_app_state(request).ollama_client
