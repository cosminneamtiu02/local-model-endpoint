"""FastAPI application factory."""

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.deps import get_settings
from app.api.errors import register_exception_handlers
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
    # ``request_id="lifespan"`` is a sentinel so a jq filter on per-request
    # request_id keeps lifespan events visible (greppable as a single
    # log-stream slice rather than dropping out of correlated views).
    # Log host/port separately rather than the full URL so a future
    # userinfo-bearing form (unusual for Ollama, possible behind a reverse
    # proxy) cannot leak credentials into stdout.
    logger.info(
        "app_startup",
        request_id="lifespan",
        env=settings.app_env,
        version=application.version,
        bind_host=settings.bind_host,
        bind_port=settings.bind_port,
        ollama_host=settings.ollama_host.host,
        ollama_port=settings.ollama_host.port,
        log_level=settings.log_level,
    )
    start_monotonic = time.monotonic()
    try:
        async with lifespan_resources(settings) as state:
            application.state.context = state
            logger.info("lifespan_resources_ready", env=settings.app_env)
            try:
                yield
            finally:
                # uptime_ms keeps the time-unit consistent with the
                # request_completed log line's duration_ms field.
                logger.info(
                    "app_shutdown",
                    request_id="lifespan",
                    version=application.version,
                    env=settings.app_env,
                    uptime_ms=int((time.monotonic() - start_monotonic) * 1000),
                )
    except Exception:
        # A resource-construction failure (settings drift, OllamaClient
        # connect-time issue, etc.) would otherwise propagate as an opaque
        # uvicorn traceback. Log a structured ``app_startup_failed`` event
        # so the operator gets a single-line cause + correlation surface.
        logger.exception("app_startup_failed", request_id="lifespan", env=settings.app_env)
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
