"""Unit tests for FastAPI dependency factories in app/api/deps.py.

The defensive ``isinstance(state, AppState)`` guard inside
``get_app_state`` exists without a TDD partner unless these tests run —
they exercise the misconfigured-app branches so a future refactor of
AppState construction cannot break the type-narrowing without a red bar.
"""

import pytest
import structlog
from fastapi import FastAPI
from starlette.requests import Request

from app.api.app_state import AppState
from app.api.deps import audit_lip_env_typos, get_app_state, get_ollama_client, get_settings
from app.exceptions import InternalError


def _request_for(app: FastAPI) -> Request:
    """Build a minimal ``Request`` whose ``request.app`` is the given app.

    ``get_app_state`` only reads ``request.app.state.context``; everything
    else on the Request object is irrelevant. Building from the ASGI scope
    avoids depending on TestClient and keeps these tests pure-unit.
    """
    scope: dict[str, object] = {
        "type": "http",
        "app": app,
        "headers": [],
        "method": "GET",
        "path": "/",
        "query_string": b"",
    }
    return Request(scope)


def test_get_app_state_when_context_missing_raises_internal_error() -> None:
    """A misconfigured app (lifespan didn't run) must surface as InternalError.

    Without this branch, the route handler would AttributeError on
    ``request.app.state.context.ollama_client`` and ship a bare 500
    instead of the typed RFC 7807 problem+json envelope.
    """
    app = FastAPI()
    request = _request_for(app)
    # ``match=`` pins the typed code so a future second InternalError
    # raise-site in ``get_app_state`` cannot silently shadow this branch's
    # contract — the test asserts *which* invariant fired, not just that
    # ``InternalError`` was raised somewhere.
    with pytest.raises(InternalError, match=InternalError.code):
        get_app_state(request)


def test_get_app_state_when_context_wrong_type_raises_internal_error() -> None:
    """A wrong-typed ``app.state.context`` must surface as InternalError.

    e.g. a raw dict left over from a stale test fixture must NOT surface
    as an attribute error deep inside ``get_ollama_client``.
    """
    app = FastAPI()
    app.state.context = {"ollama_client": "not-actually-a-client"}
    request = _request_for(app)
    with pytest.raises(InternalError, match=InternalError.code):
        get_app_state(request)


async def test_get_app_state_returns_lifespan_appstate_on_happy_path() -> None:
    """When ``app.state.context`` is a valid AppState, get_app_state returns it.

    The ``async with`` wrapping is load-bearing: ``OllamaClient.__init__``
    eagerly constructs ``httpx.AsyncClient`` (a transport pool open until
    aclose). Sibling ollama-client tests pair construction with explicit
    teardown; without the context manager here, ``filterwarnings=["error"]``
    would flip a future httpx-version pool-leak warning into a session-killing
    failure.
    """
    from app.features.inference import OllamaClient

    app = FastAPI()
    async with OllamaClient(base_url="http://127.0.0.1:11434") as client:
        state = AppState(ollama_client=client)
        app.state.context = state
        request = _request_for(app)

        assert get_app_state(request) is state


async def test_get_ollama_client_delegates_through_get_app_state() -> None:
    """``get_ollama_client`` returns the same client identity that AppState carries.

    It is a thin reader on top of ``get_app_state``. Wrapped in
    ``async with`` for the same pool-leak reason as the sibling
    happy-path test above.
    """
    from app.features.inference import OllamaClient

    app = FastAPI()
    async with OllamaClient(base_url="http://127.0.0.1:11434") as client:
        app.state.context = AppState(ollama_client=client)
        request = _request_for(app)

        assert get_ollama_client(request) is client


def test_audit_lip_env_typos_warns_on_unknown_lip_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo'd ``LIP_*`` env var should surface as a structlog warning.

    CLAUDE.md "never add an env var without adding it to Settings"
    relies on this audit, since pydantic-settings 2.14 silently ignores
    extras at the env-source layer.
    """
    monkeypatch.setenv("LIP_BOGUS_TYPO_VAR", "x")
    with structlog.testing.capture_logs() as captured:
        audit_lip_env_typos()
    warnings = [entry for entry in captured if entry.get("event") == "unknown_lip_env_vars_ignored"]
    assert len(warnings) == 1
    assert "LIP_BOGUS_TYPO_VAR" in warnings[0]["env_vars"]


def test_audit_lip_env_typos_does_not_warn_when_all_env_vars_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: every declared Settings field set → no audit warning fires.

    Loops over ``Settings.model_fields`` rather than picking one name so
    a future field added to Settings is auto-covered. The audit's
    declared-set-construction (which expands ``validation_alias`` /
    ``AliasChoices`` per field) is exercised against every field, not
    just one — defeating the regression where a future ADR adding alias
    expansion broke for a single field while one-field tests stayed
    green.
    """
    from app.core.config import Settings

    for name in Settings.model_fields:
        monkeypatch.setenv(f"LIP_{name.upper()}", "x")
    with structlog.testing.capture_logs() as captured:
        audit_lip_env_typos()
    assert not [entry for entry in captured if entry.get("event") == "unknown_lip_env_vars_ignored"]


def test_audit_lip_env_typos_catches_lowercase_typo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lowercase ``lip_*`` typo must also surface as an audit warning.

    pydantic-settings 2.14 sets ``case_sensitive=False`` on Settings, so it
    folds ``lip_ollma_host=...`` while looking for ``LIP_OLLAMA_HOST`` —
    the names don't match after fold and pydantic silently ignores it.
    The audit's ``str.startswith("LIP_")`` is case-sensitive, so a naive
    implementation would also miss the lowercase form, defeating ADR-014.
    The case-fold-symmetric prefix-match upper-cases ``name`` before the
    ``startswith`` test; this regression test pins that discipline.
    """
    monkeypatch.setenv("lip_bogus_typo_var", "x")
    with structlog.testing.capture_logs() as captured:
        audit_lip_env_typos()
    warnings = [entry for entry in captured if entry.get("event") == "unknown_lip_env_vars_ignored"]
    assert len(warnings) == 1
    # The audit upper-cases the surfaced names so a single jq filter
    # `select(.env_vars[] | startswith("LIP_"))` matches both case forms.
    assert "LIP_BOGUS_TYPO_VAR" in warnings[0]["env_vars"]


def test_audit_lip_env_typos_no_ops_when_env_prefix_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Settings.model_config['env_prefix'] is empty, the audit must
    no-op rather than surfacing every shell env var as an "unknown LIP".

    The empty-prefix short-circuit at ``deps.py`` is the lockstep partner
    of a future ADR removing the ``LIP_`` prefix entirely. Without this
    test the branch is uncovered (line 57 in coverage gap) and a refactor
    that drops the early-return would silently surface ``PATH``, ``HOME``,
    and every other shell variable as a typo'd LIP env var.
    """
    from app.core.config import Settings

    monkeypatch.setitem(Settings.model_config, "env_prefix", "")
    monkeypatch.setenv("LIP_LOG_LEVEL", "warning")
    monkeypatch.setenv("PATH", "/dummy")
    with structlog.testing.capture_logs() as captured:
        audit_lip_env_typos()
    assert not [entry for entry in captured if entry.get("event") == "unknown_lip_env_vars_ignored"]


def test_audit_lip_env_typos_de_dups_case_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting both ``LIP_BOGUS=x`` and ``lip_bogus=y`` produces ONE warning.

    The audit folds env-var names to upper before set-membership, so two
    case forms of the same logical typo collapse to a single set entry.
    A future regression that drops the case-fold on the iteration side
    (``for name in os.environ`` without ``.upper()``) would silently emit
    two warning lines for one typo and inflate operator log volume on
    transitional ``set -a`` migrations.
    """
    monkeypatch.setenv("LIP_BOGUS_TYPO_VAR", "x")
    monkeypatch.setenv("lip_bogus_typo_var", "y")
    with structlog.testing.capture_logs() as captured:
        audit_lip_env_typos()
    warnings = [entry for entry in captured if entry.get("event") == "unknown_lip_env_vars_ignored"]
    assert len(warnings) == 1
    # Exactly ONE entry in the env_vars list (the upper-cased form),
    # not two.
    assert warnings[0]["env_vars"].count("LIP_BOGUS_TYPO_VAR") == 1


def test_get_settings_construction_no_longer_emits_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``get_settings`` no longer side-effects on env-var typos.

    The audit is now a separate ``audit_lip_env_typos`` call, fired from
    ``create_app`` AFTER ``configure_logging``. ``get_settings`` itself
    must therefore stay log-silent — otherwise the orphaned warning would
    re-introduce the orphaned-non-JSON-line bug this split fixed.
    """
    monkeypatch.setenv("LIP_BOGUS_TYPO_VAR", "x")
    # No leading/trailing ``cache_clear()``: the autouse
    # ``_reset_settings_cache`` fixture in ``tests/conftest.py`` already
    # clears the cache before every test, so manual clears here would be
    # dead defensive code (matches the ``test_config.py`` convention).
    with structlog.testing.capture_logs() as captured:
        get_settings()
    assert captured == []
