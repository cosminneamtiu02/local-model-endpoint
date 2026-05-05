"""FastAPI application factory."""

import time
from asyncio import CancelledError
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from importlib import metadata as _metadata
from typing import Final, NamedTuple

import structlog
from fastapi import FastAPI

from app.api.deps import audit_lip_env_typos, get_settings
from app.api.exception_handlers import register_exception_handlers
from app.api.request_id_middleware import configure_middleware
from app.api.router_registry import lifespan_resources, register_routers
from app.core.logging import EXC_MESSAGE_PREVIEW_MAX_CHARS, configure_logging, elapsed_ms

logger = structlog.get_logger(__name__)


class _AppVersionResolution(NamedTuple):
    """Result of ``_resolve_app_version`` — version string + optional exception.

    NamedTuple (rather than a bare tuple) so ``.version`` / ``.error``
    read sites self-document instead of relying on ``[0]`` / ``[1]``
    positional indexing in the dispatch helper below.
    """

    version: str
    error: BaseException | None


def _resolve_app_version() -> _AppVersionResolution:
    """Return ``_AppVersionResolution(version, error)`` for the LIP package.

    Single source of truth shared with ``OllamaClient._build_user_agent`` so
    a future bump in ``pyproject.toml`` flows automatically into both the
    OpenAPI ``info.version`` field and the User-Agent header — no second
    hand-edited literal to remember. Returns the resolution exception (if
    any) rather than logging it because this function is called at module-
    import time, BEFORE ``configure_logging`` runs in ``create_app``; the
    caller emits the warning post-``configure_logging`` so the line lands
    as JSON in production rather than as orphaned dev-format text mid-stream.
    """
    try:
        return _AppVersionResolution(_metadata.version("lip-backend"), None)
    except _metadata.PackageNotFoundError as exc:
        return _AppVersionResolution("unknown", exc)
    except Exception as exc:  # noqa: BLE001 — defense-in-depth at module-singleton boot
        # A corrupted dist-info under editable-install layouts can raise
        # non-PackageNotFoundError (KeyError / ValueError from
        # importlib.metadata internals). Returning the exception keeps the
        # failure visible without crashing module import; the caller emits
        # the structured warning after structlog is configured.
        return _AppVersionResolution("unknown", exc)


_APP_VERSION_RESOLUTION: Final[_AppVersionResolution] = _resolve_app_version()
_APP_VERSION: Final[str] = _APP_VERSION_RESOLUTION.version
"""LIP package version, computed once per process. See ``_resolve_app_version``."""


def _emit_app_version_resolve_failure() -> None:
    """Emit the deferred warning if ``_resolve_app_version`` failed at import.

    Called from ``create_app`` AFTER ``configure_logging`` so the warning
    ships through the configured renderer (JSON in production, console in
    dev) rather than the unconfigured-structlog default chain that would
    drop the line silently or render it without redaction processors.
    """
    exc = _APP_VERSION_RESOLUTION.error
    if exc is None:
        return
    if isinstance(exc, _metadata.PackageNotFoundError):
        # ``phase="startup"`` matches the ``audit_lip_env_typos`` discipline
        # so a single jq filter ``select(.phase == "startup")`` finds every
        # pre-lifespan diagnostic uniformly — symmetric with ``phase="lifespan"``
        # (router_registry.lifespan_resources) and ``phase="request"``
        # (RequestIdMiddleware).
        logger.warning(
            "app_version_resolve_failed",
            reason="package_not_found",
            phase="startup",
        )
        return
    # ``logger.warning(..., exc_type=..., exc_message=...)`` ships the
    # exception identity without ``exc_info=True`` — the traceback is
    # unrecoverable across the module-import → ``create_app`` boundary
    # anyway, so encoding the type+preview here is a faithful record.
    logger.warning(
        "app_version_resolve_failed",
        reason="unexpected",
        exc_type=type(exc).__name__,
        exc_message=str(exc)[:EXC_MESSAGE_PREVIEW_MAX_CHARS],
        phase="startup",
    )


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
    # NOTE: ``bind_host`` / ``bind_port`` reflect the configured Settings
    # values (driven by ``LIP_BIND_HOST`` / ``LIP_BIND_PORT``), not the
    # actual uvicorn-bound socket. ``python -m app`` threads them into
    # ``uvicorn.run`` so they match in production; an ad-hoc
    # ``uvicorn app.main:app --host X --port Y`` invocation would advertise
    # the Settings values here while uvicorn binds elsewhere — uvicorn's
    # own startup line is the source of truth for the actual bind.
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
    start = time.perf_counter()
    shutdown_started: float | None = None
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
            except CancelledError:
                # SIGTERM / Ctrl-C surfaces here as CancelledError raised by
                # uvicorn's signal handler. Discriminated from the broader
                # ``except BaseException`` arm so the ``app_shutdown`` line
                # records ``reason="cancelled"`` (not ``"exception"``) on the
                # clean-shutdown path; operator filters keying on
                # ``reason="exception"`` then page only on real failures.
                shutdown_reason = "cancelled"
                raise
            except BaseException:
                # Shutdown reason captured here so the ``app_shutdown`` line
                # in the outer ``finally`` records that the body raised a
                # non-cancellation exception (e.g. a stuck route handler that
                # surfaces during teardown). Re-raises so the cause still
                # surfaces to the outer arms.
                shutdown_reason = "exception"
                raise
            finally:
                # ``app_shutdown`` records the moment the yield window
                # exited; ``app_shutdown_completed`` (emitted in the outer
                # ``finally`` below, after AsyncExitStack unwinds) records
                # the moment teardown finished. The pair lets operators
                # bound resource-teardown duration (e.g. a stuck httpx
                # pool drain) without joining log lines by request_id.
                shutdown_started = time.perf_counter()
                logger.info(
                    "app_shutdown",
                    phase="lifespan",
                    reason=shutdown_reason,
                    version=application.version,
                    env=settings.app_env,
                    uptime_ms=elapsed_ms(start),
                )
                # Drop the torn-down AppState reference so a stray request
                # arriving after lifespan exits raises ``InternalError`` via
                # ``get_app_state`` (the typed ``isinstance`` guard) rather
                # than returning a torn-down AppState whose OllamaClient
                # has already had ``__aexit__`` called on it. The
                # ``suppress(AttributeError)`` covers the path where
                # ``application.state.context`` was never assigned
                # (resource construction raised before the
                # ``application.state.context = state`` assignment above).
                with suppress(AttributeError):
                    delattr(application.state, "context")
    except CancelledError:
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
        # ``Exception`` (not ``BaseException``) so ``CancelledError``
        # propagates through its own arm above — cancellation is normal
        # shutdown traffic and should not page.
        # ``KeyboardInterrupt`` / ``SystemExit`` ride past both arms and
        # only the outer ``finally`` (``app_shutdown_completed`` with
        # ``reason="exception"``) sees them; that's intentional, paging
        # on operator-initiated SIGINT would also be alert-fatigue.
        event_name = "app_shutdown_failed" if entered_yield else "app_startup_failed"
        logger.critical(
            event_name,
            phase="lifespan",
            env=settings.app_env,
            exc_info=True,
        )
        raise
    finally:
        # Outer finally fires on every exit path (clean / cancelled /
        # exception) AFTER ``async with lifespan_resources`` has unwound
        # — so ``teardown_ms`` bounds the post-yield resource-close
        # duration. Gate on ``shutdown_started`` so a startup-time failure
        # (resources never reached the inner finally) doesn't emit a
        # confusing teardown line for a teardown that never ran.
        if shutdown_started is not None:
            logger.info(
                "app_shutdown_completed",
                phase="lifespan",
                reason=shutdown_reason,
                env=settings.app_env,
                teardown_ms=elapsed_ms(shutdown_started),
            )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    is_prod = settings.app_env == "production"

    configure_logging(log_level=settings.log_level, json_output=is_prod)
    # Both warnings below MUST emit AFTER ``configure_logging`` so the
    # lines land as JSON in production (vs. the unconfigured-structlog
    # default chain that drops them silently or renders them without the
    # redaction processor).
    _emit_app_version_resolve_failure()
    audit_lip_env_typos()

    application = FastAPI(
        title="Local Inference Provider",
        description=(
            "FastAPI service wrapping a local Ollama daemon. "
            "Exposes a stable backend-agnostic inference contract to "
            "local consumer backend projects."
        ),
        version=_APP_VERSION,
        # ``contact`` and ``license_info`` ride into the OpenAPI ``info``
        # block so consumers generating SDKs from /openapi.json inherit
        # license metadata uniformly. Sourced from pyproject.toml's
        # ``authors`` + ``license`` fields (kept in sync by hand here;
        # codegen from package metadata is overkill for two short literals).
        contact={"name": "Cosmin Neamtiu"},
        license_info={"name": "MIT"},
        lifespan=lifespan,
        # ``redirect_slashes=False`` makes a trailing-slash mismatch
        # surface as a clean 404 problem+json (which the typed exception
        # chain already handles via ``NotFoundError``) instead of a 307
        # redirect that some httpx-based consumers drop the body on for
        # POST. The wire contract is "use the path the OpenAPI spec
        # advertises"; auto-redirecting to a different path silently
        # papers over an SDK bug at the cost of one round-trip.
        redirect_slashes=False,
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
