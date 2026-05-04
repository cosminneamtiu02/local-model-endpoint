"""Registry of feature routers and lifespan resources.

main.py imports register_routers and lifespan_resources here, never
directly from features/. New features add their entries below as they
land — main.py stays unchanged feature after feature.
"""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.app_state import AppState
from app.api.health_router import router as health_router
from app.core.config import Settings
from app.features.inference import OllamaClient


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

    ``settings`` is hand-passed (rather than reached internally via
    ``get_settings()``) so test fixtures can vary Settings under
    monkeypatch without going through the @lru_cache(maxsize=1) carve-out
    in ``app.api.deps.get_settings``. Production callers (currently only
    ``app.main.lifespan``) MUST pass ``get_settings()`` to preserve the
    cached-Settings invariant — bypassing it would construct two Settings
    instances per request lifetime.

    Resources are pushed onto an ``AsyncExitStack`` so any sibling
    resource added later this lifespan is torn down in LIFO order even
    if a downstream construction fails — and ``__aexit__`` receives the
    live exc_info on body errors, instead of the manual ``(None, None,
    None)`` triple a hand-rolled call site would pass. Without the
    stack, a future sibling whose ``__aenter__`` raised between
    OllamaClient construction and the yield would leak the httpx pool.

    ``phase="lifespan"`` is bound on the contextvars stack across the
    full lifespan window (construction, yield, and the AsyncExitStack
    unwind teardown). The yield window is safe because
    :class:`RequestIdMiddleware` calls ``clear_contextvars()`` at the
    start of every HTTP request, so request-handler tasks do not inherit
    the sentinel — request logs always carry only request-scope context.
    Lifespan-internal logs (``OllamaClient.__aenter__`` / ``__aexit__``,
    ``app_startup``, ``app_shutdown``) all see ``phase="lifespan"``,
    keeping grep-based correlation intact.
    """
    async with AsyncExitStack() as stack:
        # Push the contextvar binding onto the stack FIRST so it unwinds
        # LAST (LIFO): subsequent resource __aexit__ calls — including
        # OllamaClient's — fire while ``phase="lifespan"`` is still bound.
        # ``bound_contextvars`` is a sync context manager; ``enter_context``
        # (not ``enter_async_context``) is the correct method.
        stack.enter_context(structlog.contextvars.bound_contextvars(phase="lifespan"))
        client = await stack.enter_async_context(
            OllamaClient(base_url=str(settings.ollama_host)),
        )
        state = AppState(ollama_client=client)
        yield state
