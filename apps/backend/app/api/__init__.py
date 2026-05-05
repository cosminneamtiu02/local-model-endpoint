"""API layer — middleware, exception handlers, shared deps, router registry.

Curated public surface. Per-file imports work too, but consumers that go
through the package surface are insulated from internal file moves.
"""

from app.api.app_state import AppState
from app.api.deps import get_app_state, get_ollama_client, get_settings
from app.api.exception_handler_registry import register_exception_handlers
from app.api.request_id_middleware import configure_middleware
from app.api.router_registry import lifespan_resources, register_routers

# ``RequestIdMiddleware`` is intentionally NOT re-exported. ``configure_middleware``
# is the single mounting point — exporting the class here would invite a future
# feature to bypass the registration helper and ``add_middleware`` it directly,
# defeating the "single mounting point" intent (CLAUDE.md "one way to do each thing").
__all__ = [
    "AppState",
    "configure_middleware",
    "get_app_state",
    "get_ollama_client",
    "get_settings",
    "lifespan_resources",
    "register_exception_handlers",
    "register_routers",
]
