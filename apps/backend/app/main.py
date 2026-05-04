"""FastAPI application factory."""

import asyncio
import contextlib
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib import metadata as _metadata

import structlog
from fastapi import FastAPI

from app.api.deps import get_settings
from app.api.exception_handlers import register_exception_handlers
from app.api.request_id_middleware import configure_middleware
from app.api.router_registry import lifespan_resources, register_routers
from app.core.logging import configure_logging, elapsed_ms

logger = structlog.get_logger(__name__)


def _resolve_app_version() -> str:
    """Return the LIP package version from importlib.metadata, or ``"unknown"``.

    Single source of truth shared with ``OllamaClient._build_user_agent`` so
    a future bump in ``pyproject.toml`` flows automatically into both the
    OpenAPI ``info.version`` field and the User-Agent header — no second
    hand-edited literal to remember.
    """
    try:
        return _metadata.version("lip-backend")
    except _metadata.PackageNotFoundError:
        # Editable install context where importlib.metadata can't see the
        # dist-info — surface as ``unknown`` rather than crash the factory.
        # Same fallback shape OllamaClient uses; the warning lives there
        # so this helper stays pure-data for ``FastAPI(version=...)``.
        return "unknown"


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
        # Safety-clamp escape hatches surfaced at startup so a misconfigured
        # public-bind / external-Ollama deployment is greppable from a single
        # log line — operators searching for ``allow_public_bind=true`` can
        # find the misconfigured-app instance without diffing every env var.
        allow_external_ollama=settings.allow_external_ollama,
        allow_public_bind=settings.allow_public_bind,
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
                    uptime_ms=elapsed_ms(start_monotonic, now=time.monotonic),
                )
                # Drop the torn-down AppState reference so a stray request
                # arriving after lifespan exits raises ``InternalError`` via
                # ``get_app_state`` (the typed ``isinstance`` guard) rather
                # than returning a torn-down AppState whose OllamaClient
                # has already had ``__aexit__`` called on it. The
                # ``contextlib.suppress(AttributeError)`` covers the path
                # where ``application.state.context`` was never assigned
                # (resource construction raised before line 65).
                with contextlib.suppress(AttributeError):
                    delattr(application.state, "context")
    except asyncio.CancelledError:
        # Clean SIGTERM / Ctrl-C cancellation during teardown is normal;
        # uvicorn's signal handler raises CancelledError into the lifespan
        # generator on shutdown. Logging this at ``critical`` would alert-
        # fatigue operator paging that keys on level=CRITICAL. Drop to ``info``
        # for shutdown-cancel; ``app_startup_cancelled`` is the rarer-but-
        # also-not-critical case (e.g. uvicorn aborted before resources
        # constructed). The bare ``raise`` preserves cancellation propagation.
        event_name = "app_shutdown_cancelled" if entered_yield else "app_startup_cancelled"
        logger.info(event_name, phase="lifespan", env=settings.app_env)
        raise
    except Exception:
        # A resource-construction failure (settings drift, OllamaClient
        # connect-time issue, etc.) would otherwise propagate as an opaque
        # uvicorn traceback. Logged at ``critical`` (NOT ``logger.exception``,
        # which is the in-except idiom elsewhere in the codebase) because
        # operator paging keys on level=CRITICAL; ``exc_info=True`` is
        # explicit because critical isn't auto-traceback-attaching like
        # ``exception`` is. ``entered_yield`` discriminates startup vs
        # shutdown so the event name routes to the correct runbook.
        #
        # ``Exception`` (not ``BaseException``) so ``CancelledError`` /
        # ``KeyboardInterrupt`` / ``SystemExit`` propagate through their own
        # arms — cancellation is normal shutdown traffic and should not page.
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
        version=_resolve_app_version(),
        lifespan=lifespan,
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )

    configure_middleware(application)
    register_exception_handlers(application)
    register_routers(application)

    return application


# Module-level binding required by uvicorn's ``"module:attr"`` string-lookup
# (``uv run python -m app --reload`` resolves ``app.main:app`` at process
# start). Side effects: importing ``app.main`` from a test triggers full
# create_app() construction including Settings load + structlog configure
# + RequestIdMiddleware mount. Tests that want a different Settings env
# call ``create_app()`` again under monkeypatch — the second app instance
# is intentional, not a leak.
app = create_app()
