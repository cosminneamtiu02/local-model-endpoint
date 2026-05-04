"""Typed FastAPI app state container — replaces ad-hoc app.state.X attributes.

Lifespan constructs an AppState once at startup and stashes it as
app.state.context. Depends factories read fields off it without cast().
"""

from dataclasses import dataclass

from app.features.inference import OllamaClient


@dataclass(slots=True, frozen=True)
class AppState:
    """Lifespan-managed application state.

    Add new fields here when new lifespan-managed resources arrive
    (semaphore for LIP-E004-F001, idle watchdog for LIP-E005-F002,
    etc.). dataclass over Pydantic to avoid pydantic-validation overhead
    on objects holding open httpx clients.
    """

    ollama_client: OllamaClient
