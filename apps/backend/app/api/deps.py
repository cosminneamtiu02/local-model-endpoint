"""Shared FastAPI dependencies."""

from functools import lru_cache
from typing import cast

from fastapi import Request

from app.core.config import Settings
from app.features.inference.repository.ollama_client import OllamaClient


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()  # pyright: ignore[reportCallIssue]  # pydantic-settings loads fields from env


def get_ollama_client(request: Request) -> OllamaClient:
    """Return the lifespan-managed OllamaClient stored on app.state.

    The client is constructed in main.lifespan at startup and closed at
    shutdown; the same instance is returned across all requests within
    one app instance. cast() is required because Starlette's State is
    typed as Any.
    """
    # ruff TC006 prefers the quoted form to avoid runtime type resolution
    return cast("OllamaClient", request.app.state.ollama_client)
