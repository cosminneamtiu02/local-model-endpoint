"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api.deps import get_settings
from app.api.errors import register_exception_handlers
from app.api.health_router import router as health_router
from app.api.middleware import configure_middleware
from app.core.logging import configure_logging
from app.features.inference.repository.ollama_client import OllamaClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan hook.

    Constructs the OllamaClient at startup and stores it on app.state;
    closes it at shutdown. The warm-up dummy inference (LIP-E005-F001)
    will be layered on top of this client when that feature lands.
    """
    settings = get_settings()
    app.state.ollama_client = OllamaClient(base_url=settings.ollama_host)
    try:
        yield
    finally:
        await app.state.ollama_client.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    configure_logging(
        log_level=settings.log_level,
        json_output=settings.app_env == "production",
    )

    is_prod = settings.app_env == "production"
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

    # Health endpoint at root, outside /api/v1/
    application.include_router(health_router)

    # Inference routes under /api/v1/. The LIP feature router is included
    # here when LIP-E001-F002 lands during feature-dev.
    api_v1 = APIRouter(prefix="/api/v1")
    application.include_router(api_v1)

    return application


app = create_app()
