"""Registry of feature routers and lifespan resources.

main.py imports register_routers and lifespan_resources here, never
directly from features/. New features add their entries below as they
land — main.py stays unchanged feature after feature.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api.state import AppState
from app.core.config import Settings
from app.features.inference.repository import OllamaClient


def register_routers(application: FastAPI) -> None:
    """Mount all feature routers under their version prefixes."""
    v1 = APIRouter(prefix="/v1")
    # Inference router included here when LIP-E001-F002 lands during feature-dev.
    application.include_router(v1)


@asynccontextmanager
async def lifespan_resources(settings: Settings) -> AsyncIterator[AppState]:
    """Construct and tear down all lifespan-managed resources.

    Centralizing this here means main.py's lifespan stays a one-liner
    even as features add resources (semaphore, idle watchdog, etc.).
    """
    client = OllamaClient(base_url=str(settings.lip_ollama_host))
    state = AppState(ollama_client=client)
    try:
        yield state
    finally:
        await client.close()
