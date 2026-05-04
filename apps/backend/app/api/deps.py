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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    # ``Settings.model_validate({})`` runs the BaseSettings env / .env load
    # path the same way ``Settings()`` does, but goes through Pydantic's
    # typed ``model_validate`` entry point so pyright doesn't see a
    # dynamic-init false-positive. Avoids the ``# pyright: ignore`` escape
    # hatch and keeps the construction site contract-clean.
    settings = Settings.model_validate({})
    # See ``Settings.__doc__`` — pydantic-settings 2.14 silently ignores
    # unknown ``LIP_*`` env vars at the env-source layer. This ``os.environ``
    # enumeration is the only known way to surface that, fired once per
    # process via @lru_cache. The env-prefix is read from
    # ``Settings.model_config`` directly so a future ADR renaming ``LIP_``
    # propagates here automatically.
    env_prefix = Settings.model_config.get("env_prefix") or ""
    declared = {f"{env_prefix}{name.upper()}" for name in Settings.model_fields}
    actual = {name for name in os.environ if name.startswith(env_prefix)}
    unknown = sorted(actual - declared)
    if unknown:
        # ``phase="startup"`` keeps this warning grep-compatible with the
        # rest of the lifecycle taxonomy (lifespan logs carry
        # ``phase="lifespan"``, request logs carry ``phase="request"``).
        # ``get_settings()`` first-fires inside ``create_app`` BEFORE the
        # lifespan binds ``phase``, so the field would otherwise be missing
        # exactly on the line operators grep when triaging
        # "why didn't my env override take effect?".
        logger.warning("unknown_lip_env_vars_ignored", env_vars=unknown, phase="startup")
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
        # Emit a named diagnostic before the typed raise so operators
        # paging on ``domain_error_5xx_raised`` can distinguish "AppState
        # invariant violated" (lifespan never ran / late request after
        # teardown — different runbook) from "real handler crash".
        logger.warning(
            "app_state_unavailable",
            path=request.url.path,
            has_context_attr=hasattr(request.app.state, "context"),
        )
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
