"""FastAPI application factory."""

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.deps import get_settings
from app.api.exception_handlers import register_exception_handlers
from app.api.middleware import configure_middleware
from app.api.router_registry import lifespan_resources, register_routers
from app.core.logging import configure_logging

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan hook.

    Constructs lifespan-managed resources via lifespan_resources() and
    parks the resulting AppState on ``application.state.context`` so
    feature dependencies can read them via Depends factories.
    """
    settings = get_settings()
    # ``phase="lifespan"`` is the sentinel so a jq filter ``select(.phase ==
    # "lifespan")`` greps the lifespan slice without violating the UUID-shape
    # contract that ``request_id`` carries everywhere else (the middleware +
    # exception handler both enforce UUID-shape on ``request_id``; reusing
    # that key for a non-UUID literal would break consumer pattern-matchers).
    # Log host/port separately rather than the full URL so a future
    # userinfo-bearing form (unusual for Ollama, possible behind a reverse
    # proxy) cannot leak credentials into stdout.
    logger.info(
        "app_startup",
        phase="lifespan",
        env=settings.app_env,
        version=application.version,
        bind_host=settings.bind_host,
        bind_port=settings.bind_port,
        ollama_host=settings.ollama_host.host,
        ollama_port=settings.ollama_host.port,
        log_level=settings.log_level,
    )
    start_monotonic = time.monotonic()
    shutdown_reason = "clean"
    # Track whether we entered the resource-yield window so the outer
    # except can distinguish a startup-time failure (resource construction
    # threw) from a shutdown-time failure (resource teardown threw). Logging
    # both as ``app_startup_failed`` would silently misroute operator pages
    # — startup pages route to "is the daemon up?" while shutdown pages
    # route to "did the daemon clean up?".
    entered_yield = False
    try:
        async with lifespan_resources(settings) as state:
            application.state.context = state
            entered_yield = True
            logger.info("lifespan_resources_ready", phase="lifespan", env=settings.app_env)
            try:
                yield
            except BaseException:
                # Shutdown reason captured here so the ``app_shutdown`` line
                # in the outer ``finally`` records whether the body unwound
                # cleanly or was interrupted (SIGTERM / exception inside the
                # request loop). Re-raises so the cause still surfaces.
                shutdown_reason = "exception"
                raise
            finally:
                # uptime_ms keeps the time-unit consistent with the
                # request_completed log line's duration_ms field.
                logger.info(
                    "app_shutdown",
                    phase="lifespan",
                    reason=shutdown_reason,
                    version=application.version,
                    env=settings.app_env,
                    uptime_ms=int((time.monotonic() - start_monotonic) * 1000),
                )
    except Exception:
        # A resource-construction failure (settings drift, OllamaClient
        # connect-time issue, etc.) would otherwise propagate as an opaque
        # uvicorn traceback. Logged at ``critical`` because no traffic can
        # be served — operator alerting keyed on level should page on this.
        # ``entered_yield`` discriminates startup vs shutdown so the event
        # name routes to the correct runbook.
        event_name = "app_shutdown_failed" if entered_yield else "app_startup_failed"
        logger.critical(
            event_name,
            phase="lifespan",
            env=settings.app_env,
            exc_info=True,
        )
        raise


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    is_prod = settings.app_env == "production"

    configure_logging(log_level=settings.log_level, json_output=is_prod)

    application = FastAPI(
        title="Local Inference Provider",
        description=(
            "FastAPI service wrapping a local Ollama daemon. "
            "Exposes a stable backend-agnostic inference contract to "
            "local consumer backend projects."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )

    configure_middleware(application)
    register_exception_handlers(application)
    register_routers(application)

    return application


app = create_app()
