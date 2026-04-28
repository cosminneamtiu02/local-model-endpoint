"""API layer — middleware, exception handlers, shared deps, router registry.

Curated public surface. Per-file imports work too, but consumers that go
through the package surface are insulated from internal file moves.
"""

from app.api.app_state import AppState
from app.api.deps import get_app_state, get_ollama_client, get_settings
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestIdMiddleware, configure_middleware
from app.api.router_registry import lifespan_resources, register_routers

__all__ = [
    "AppState",
    "RequestIdMiddleware",
    "configure_middleware",
    "get_app_state",
    "get_ollama_client",
    "get_settings",
    "lifespan_resources",
    "register_exception_handlers",
    "register_routers",
]
