"""Shared FastAPI dependencies."""

import os
from functools import lru_cache

import structlog
from fastapi import Request

from app.api.app_state import AppState
from app.core.config import Settings
from app.exceptions import InternalError
from app.features.inference import OllamaClient

logger = structlog.get_logger(__name__)

_LIP_ENV_PREFIX = "LIP_"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    # ``Settings.model_validate({})`` runs the BaseSettings env / .env load
    # path the same way ``Settings()`` does, but goes through Pydantic's
    # typed ``model_validate`` entry point so pyright doesn't see a
    # dynamic-init false-positive. Avoids the ``# pyright: ignore`` escape
    # hatch and keeps the construction site contract-clean.
    settings = Settings.model_validate({})
    # CLAUDE.md mandates "never add an env var without adding it to the
    # ``Settings`` class". pydantic-settings 2.14 silently ignores unknown
    # ``LIP_*`` env vars at runtime (the ``extra="forbid"`` setting only
    # gates init kwargs, verified by
    # ``test_settings_extra_forbid_silently_ignores_unknown_env_var``). The
    # ``os.environ`` read below is an audit-only enumeration — NOT a config
    # read — and is the only known way to surface unknown ``LIP_*`` env vars
    # since pydantic-settings does not expose the keys it ignored. One
    # ``unknown_lip_env_vars_ignored`` warning fires once per process at
    # first ``get_settings()`` call (the @lru_cache ensures single-fire),
    # so a typo (``LIP_OLLMA_HOST``) is visible to the operator instead of
    # silently falling through to defaults.
    declared = {f"{_LIP_ENV_PREFIX}{name.upper()}" for name in settings.model_fields}
    actual = {name for name in os.environ if name.startswith(_LIP_ENV_PREFIX)}
    unknown = sorted(actual - declared)
    if unknown:
        logger.warning("unknown_lip_env_vars_ignored", env_vars=unknown)
    return settings


def get_app_state(request: Request) -> AppState:
    """Return the lifespan-managed AppState attached at startup.

    A typed isinstance guard catches the misconfigured-app case (lifespan
    didn't run, or ``app.state.context`` was never set) and raises a typed
    InternalError so the response stays RFC 7807 problem+json instead of
    surfacing as a bare AttributeError 500.
    """
    state: object = getattr(request.app.state, "context", None)
    if not isinstance(state, AppState):
        # ruff's RSE102 prefers ``raise X`` over ``raise X()`` for
        # parameterless exception classes — Python auto-instantiates and
        # the no-parens form makes the intent obvious.
        raise InternalError
    return state


def get_ollama_client(request: Request) -> OllamaClient:
    """Return the lifespan-managed OllamaClient.

    Reads off the typed AppState that lifespan_resources stores on
    `app.state.context` so feature handlers don't need cast() and stay
    pyright-strict.
    """
    return get_app_state(request).ollama_client
