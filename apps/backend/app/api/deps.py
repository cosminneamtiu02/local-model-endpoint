"""Shared FastAPI dependencies."""

import os
from functools import lru_cache

import structlog
from fastapi import Request

from app.api.app_state import AppState
from app.core.config import Settings
from app.core.logging import ascii_safe
from app.exceptions import InternalError
from app.features.inference import OllamaClient
from app.schemas.wire_constants import INSTANCE_PATH_MAX_CHARS

logger = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings.

    Construction goes through ``Settings.model_validate({})`` rather than
    ``Settings()``: pydantic-settings 2.14's ``model_validate`` runs the same
    env / .env load path while letting pyright see the typed construction
    surface, so the call site stays contract-clean without a
    ``# pyright: ignore`` escape hatch. ``maxsize=1`` is the FastAPI-blessed
    Settings-singleton pattern (CLAUDE.md sole-carve-out); tests use
    ``get_settings.cache_clear()`` for hermetic isolation.
    """
    return Settings.model_validate({})


def audit_lip_env_typos() -> None:
    """Surface typo'd ``LIP_*`` env vars that pydantic-settings silently ignores.

    pydantic-settings 2.14 ignores unknown env vars at the env-source layer
    (``extra="forbid"`` only fires on init kwargs). This helper enumerates
    ``os.environ`` once per process and warns about any ``LIP_*`` name that
    doesn't match a declared ``Settings`` field, so an operator with
    ``LIP_OLLMA_HOST=...`` (typo) sees a startup-time warning rather than a
    silent default-value boot.

    MUST be called from ``create_app`` AFTER ``configure_logging`` so the
    warning ships through the configured renderer (JSON in production,
    console in dev) rather than the unconfigured-structlog default chain
    that would render the line as orphaned text in an otherwise-JSON
    stream. The env-prefix is read from ``Settings.model_config`` so a
    future ADR renaming ``LIP_`` propagates here automatically.
    """
    env_prefix = Settings.model_config.get("env_prefix") or ""
    if not env_prefix:
        # ADR-014 assumes a non-empty prefix; without one, ``startswith("")``
        # would match every env var on the host and surface the operator's
        # entire shell environment as "unknown LIP". A future ADR removing
        # the prefix must update this audit in lockstep.
        return
    # Case-fold-symmetric with ``Settings.model_config["case_sensitive"]=False``:
    # ``str.startswith`` is case-sensitive, but pydantic-settings folds env-var
    # names to upper before matching declared fields. A lowercase
    # ``lip_ollma_host`` typo would otherwise be ignored by both layers —
    # this audit's whole reason for existing. Comparing both sides upper-cased
    # keeps the audit and the field-load layer in lockstep.
    env_prefix_upper = env_prefix.upper()
    # Build the declared-set from each FieldInfo so a future field that uses
    # ``Field(validation_alias="X")`` (or ``AliasChoices(...)``) is honored.
    # ``model_fields`` is keyed by Python attribute name, but pydantic-settings
    # prefers ``validation_alias`` over the prefixed name when it's set —
    # without this expansion, declaring a ``validation_alias`` would land the
    # alias as "unknown LIP" (false positive) and leave the alias-typo
    # surface unchecked (false negative). All current Settings fields have
    # ``validation_alias=None``; only the ``str`` and ``AliasChoices``
    # spellings are handled today. ``AliasPath`` (segment-list form) is NOT
    # handled — adding it before any field uses it would be pre-feature
    # scaffolding (per ADR-011); when a field declares ``AliasPath``, extend
    # this loop to iterate ``getattr(validation_alias, "path", ())`` in the
    # same PR that adds the field.
    declared: set[str] = set()
    for name, info in Settings.model_fields.items():
        declared.add(f"{env_prefix_upper}{name.upper()}")
        validation_alias = info.validation_alias
        if isinstance(validation_alias, str):
            declared.add(validation_alias.upper())
        elif validation_alias is not None:
            # ``AliasChoices`` exposes a ``.choices`` attribute carrying
            # multiple alias spellings; pydantic-settings tries each one.
            # Surface every literal-string spelling so the audit accepts
            # whichever alias the operator actually exports.
            for choice in getattr(validation_alias, "choices", ()):
                if isinstance(choice, str):
                    declared.add(choice.upper())
    # Walrus-memoize ``name.upper()`` so each env-var name is upper-cased
    # exactly once per startup audit (mirrors the ``o := ord(c)`` pattern in
    # ``app/api/request_id_middleware.py``'s C0-control scan — same
    # "compute-once, use twice" idiom).
    actual = {upper for name in os.environ if (upper := name.upper()).startswith(env_prefix_upper)}
    unknown = sorted(actual - declared)
    if unknown:
        # ``ascii_safe`` per-name defense-in-depth: POSIX permits
        # control-byte-bearing env-var names, and a malicious ``LIP_X\x1b[31mY``
        # would otherwise inject ANSI escapes into dev-mode ConsoleRenderer
        # output via this warning's structured fields. Symmetric with the
        # ``ascii_safe`` discipline applied at every other log-injection
        # vector site (``RequestIdMiddleware``'s X-Request-ID preview,
        # ``OllamaClient.chat``'s ``exc_message``).
        sanitized = [ascii_safe(name) for name in unknown]
        # ``phase="pre_lifespan"`` discriminates pre-``configure_logging``
        # diagnostics from the lifespan-window events (which carry
        # ``phase="lifespan"``). The two values are intentionally
        # disjoint: ``select(.phase == "pre_lifespan")`` finds startup
        # warnings that fired BEFORE the structlog config landed;
        # ``select(.phase == "lifespan")`` finds events from the lifespan
        # body. Request logs use ``phase="request"``. The full env-var
        # names are deliberately surfaced as a triage affordance —
        # operators searching "did this typo fire" can grep the unknown
        # set directly. CLAUDE.md's prompt-content ban applies to
        # message bodies; env-var names are operator metadata.
        # ``count`` ships alongside the list so a malformed ``.env``
        # exporting hundreds of typo'd ``LIP_*`` names doesn't force the
        # operator to ``.env_vars | length`` from the structured field —
        # symmetric with ``error_count`` on the validation handler and
        # ``message_count`` on ``OllamaClient.chat``.
        logger.warning(
            "unknown_lip_env_vars_ignored",
            env_vars=sanitized,
            count=len(sanitized),
            phase="pre_lifespan",
        )


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
        # ``ascii_safe`` mirrors the per-request ``_bounded_instance``
        # discipline in ``exception_handler_registry``: control chars in the path
        # cannot ANSI-inject into ConsoleRenderer output. Logged at
        # ``error`` (not ``warning``) because the consequence is a 500;
        # operator dashboards keyed on ``level=error`` need this signal.
        # ``phase="request"`` defense-in-depth: the middleware ordinarily
        # binds ``phase="request"`` via contextvars, but this diagnostic
        # specifically fires on the path where the middleware-bound state may
        # be missing (lifespan never ran). The literal kwarg is the
        # safety net that keeps a jq filter ``select(.phase == "request")``
        # finding this line on the misconfigured-app path.
        logger.error(
            "app_state_unavailable",
            phase="request",
            path=ascii_safe(request.url.path, max_chars=INSTANCE_PATH_MAX_CHARS),
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
