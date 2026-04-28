"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.deps import get_settings
from app.api.errors import register_exception_handlers
from app.api.health_router import router as health_router
from app.api.middleware import configure_middleware
from app.api.router_registry import lifespan_resources, register_routers
from app.core.logging import configure_logging

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Application lifespan hook.

    Constructs lifespan-managed resources via lifespan_resources() and
    parks the resulting AppState on `application.state.context` so
    feature dependencies can read them via Depends factories. The
    warm-up dummy inference (LIP-E005-F001) layers on top of this when
    that feature lands.
    """
    settings = get_settings()
    logger.info("app_startup", env=settings.app_env)
    async with lifespan_resources(settings) as state:
        application.state.context = state
        try:
            yield
        finally:
            logger.info("app_shutdown")


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
    application.include_router(health_router)
    register_routers(application)

    return application


app = create_app()
