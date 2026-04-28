"""Registry of feature routers and lifespan resources.

main.py imports register_routers and lifespan_resources here, never
directly from features/. New features add their entries below as they
land — main.py stays unchanged feature after feature.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.app_state import AppState
from app.api.health_router import router as health_router
from app.core.config import Settings
from app.features.inference.repository import OllamaClient


def register_routers(application: FastAPI) -> None:
    """Mount every router on the FastAPI app.

    Health stays at root (unversioned, liveness/readiness conventions).
    Feature routers nest under ``/v1`` once any are added; mount them
    here via ``application.include_router(feature_router, prefix="/v1")``
    so the prefix is centrally owned (each feature router declares only
    its sub-path, not the version segment).
    """
    application.include_router(health_router)


@asynccontextmanager
async def lifespan_resources(settings: Settings) -> AsyncGenerator[AppState]:
    """Construct and tear down all lifespan-managed resources.

    Centralizing this here means main.py's lifespan stays a one-liner
    even as features add resources (semaphore, idle watchdog, etc.).
    Using OllamaClient as its own async context manager guarantees
    __aexit__ runs even if construction of a future sibling resource
    fails between client creation and the yield.

    ``phase="lifespan"`` is bound on the contextvars stack ONLY during
    the construction (__aenter__) and teardown (__aexit__) windows —
    not across the yield — so request-handler tasks spawned during
    normal operation do not inherit the sentinel. Without this binding,
    ``OllamaClient.__aenter__`` / ``__aexit__`` log lines (emitted
    inside the client itself) would be missing the ``phase`` key that
    every other lifespan event carries, breaking grep-based correlation.
    """
    client = OllamaClient(base_url=str(settings.ollama_host))
    with structlog.contextvars.bound_contextvars(phase="lifespan"):
        await client.__aenter__()
    try:
        yield AppState(ollama_client=client)
    finally:
        with structlog.contextvars.bound_contextvars(phase="lifespan"):
            await client.__aexit__(None, None, None)
