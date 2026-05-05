"""Unit tests for Settings (LIP-E003-F001 + safety-clamp coverage)."""

import pytest
from pydantic import ValidationError

from app.api.deps import get_settings
from app.core.config import Settings, is_private_host
from tests._settings_factory import make_settings


def test_ollama_host_defaults_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """With LIP_OLLAMA_HOST unset, the default is the local Ollama port."""
    monkeypatch.delenv("LIP_OLLAMA_HOST", raising=False)
    settings = make_settings()
    # AnyHttpUrl normalizes to a trailing slash; compare via str().
    assert str(settings.ollama_host) == "http://localhost:11434/"


def test_ollama_host_env_var_overrides_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LIP_OLLAMA_HOST env var is reflected in Settings.ollama_host.

    The ``LIP_`` prefix is configured via ``env_prefix`` on the Settings
    SettingsConfigDict so every field reads from a uniformly-namespaced
    env var (``LIP_<UPPER_FIELD>``). pydantic-settings matches env vars
    case-insensitively by default, which is what makes the conventional
    UPPERCASE env var name map to the lowercase ``ollama_host`` field.

    The override host must be in the SSRF-clamp allowlist (loopback /
    RFC1918 / link-local) — `127.0.0.1` is the simplest legal value.
    """
    monkeypatch.setenv("LIP_OLLAMA_HOST", "http://127.0.0.1:11500")
    settings = make_settings()
    assert str(settings.ollama_host) == "http://127.0.0.1:11500/"


@pytest.mark.parametrize(
    "field_name",
    [
        "app_env",
        "log_level",
        "ollama_host",
        "allow_external_ollama",
        "allow_public_bind",
        "bind_host",
    ],
)
def test_settings_is_frozen_at_runtime(field_name: str) -> None:
    """Settings is frozen — field assignment after construction must raise.

    The ``frozen=True`` invariant is load-bearing: the
    ``_check_safety_invariants`` model_validator runs only on construction,
    so allowing post-construction assignment would let a caller bypass the
    SSRF and public-bind clamps by mutating ``ollama_host`` or
    ``allow_public_bind`` after the fact. Asserting the BEHAVIOR (assignment
    raises) instead of the FLAG (model_config["frozen"] is True) catches
    both flag drift AND a future pydantic-settings change to what
    ``frozen=True`` means.

    Parametrized over every field in Settings.model_fields so adding a new
    field in the future automatically gets the immutability guarantee
    asserted — no per-field test sweep needed.
    """
    settings = make_settings()
    with pytest.raises(ValidationError):
        # ``# pyright: ignore[reportAttributeAccessIssue]`` (not
        # ``# type: ignore[misc]``): aligns dialect with the rest of the
        # repo (12 sites use ``pyright: ignore``). frozen=True invariant
        # test — assignment must raise at runtime, not get typed-out by
        # pyright.
        setattr(settings, field_name, "bogus")  # pyright: ignore[reportAttributeAccessIssue]


def test_settings_extra_forbid_rejects_unknown_kwarg() -> None:
    """extra='forbid' rejects unknown init kwargs (the kwarg-equivalent surface)."""
    with pytest.raises(ValidationError):
        make_settings(bogus_field="x")


def test_settings_extra_forbid_silently_ignores_unknown_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extra='forbid' is enforced on init kwargs ONLY — env vars are silent.

    pydantic-settings 2.14 explicitly does NOT honor ``extra='forbid'`` for
    env-var sources. A typo like ``LIP_OLLMA_HOST=...`` in .env is silently
    ignored rather than raising at import time. Pinning this surprise so the
    cache files / future docs cannot drift back to claiming env-var rejection.

    The assertions cover BOTH halves of the contract:
    1. ``make_settings()`` constructs successfully (no ValidationError).
    2. The bogus name is dropped from the constructed instance (not landed
       on a hidden ``_extras`` field). Without the second assertion, a
       future pydantic-settings 3.x that started populating an ``_extras``
       attribute would still pass ``# must not raise`` while breaking the
       silent-ignore invariant the docstring claims to pin.
    """
    monkeypatch.setenv("LIP_BOGUS_ENV_VAR", "x")
    settings = make_settings()
    dumped = settings.model_dump()
    assert "bogus_env_var" not in dumped
    assert "bogus" not in str(dumped).lower()


def test_settings_case_sensitive_default_off() -> None:
    """case_sensitive is the pydantic-settings default; pin it so a future
    upstream default flip surfaces here instead of silently breaking
    lowercase env vars in .env files."""
    assert Settings.model_config.get("case_sensitive") is False


def test_settings_validate_default_is_true() -> None:
    """validate_default=True ensures bad defaults fail at import time.

    Pinned alongside ``test_settings_case_sensitive_default_off`` so a
    future model_config edit that flips this to False (silently allowing
    a bogus default URL through) surfaces here.
    """
    assert Settings.model_config.get("validate_default") is True


def test_settings_extra_forbid_flag_is_set() -> None:
    """``extra='forbid'`` is the model_config flag that powers the kwarg-reject
    test ``test_settings_extra_forbid_rejects_unknown_kwarg``. Pinning the
    flag directly catches a future flip to ``"allow"`` (silent kwarg pass-
    through) at the introspection layer rather than as a downstream symptom
    in the kwarg test."""
    assert Settings.model_config.get("extra") == "forbid"


def test_settings_env_prefix_is_lip() -> None:
    """``env_prefix='LIP_'`` is read at runtime by ``audit_lip_env_typos``.

    Pinning the literal here means a future ADR rename (e.g. to ``INFER_``)
    is a tripwire that forces the prefix flip, ``.env.example`` update, and
    CLAUDE.md docs change to land in lockstep instead of as silent drift.
    """
    assert Settings.model_config.get("env_prefix") == "LIP_"


def test_settings_env_ignore_empty_is_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """``env_ignore_empty=True`` means an empty ``LIP_BIND_HOST=`` falls back
    to the default rather than reaching ``_check_safety_invariants`` with
    an empty string. Pinning the BEHAVIOR (empty env var → default value)
    rather than the FLAG ensures a future model_config flip to False would
    surface as a clamp-error at import time and fail this test."""
    monkeypatch.setenv("LIP_BIND_HOST", "")
    settings = make_settings()
    assert settings.bind_host == "127.0.0.1"


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_settings_log_level_accepts_uppercase(
    monkeypatch: pytest.MonkeyPatch,
    level: str,
) -> None:
    """``LIP_LOG_LEVEL=INFO`` and ``LIP_LOG_LEVEL=info`` are both accepted.

    The ``_normalize_log_level(mode='before')`` field validator lowercases
    the incoming string so the case-sensitive ``Literal[...]`` constraint
    on ``log_level`` passes for either form. Pinning every uppercase
    variant catches a regression that drops the validator (silently
    rejecting the natural form for operators copy-pasting from stdlib
    ``logging`` docs).
    """
    monkeypatch.setenv("LIP_LOG_LEVEL", level)
    settings = make_settings()
    assert settings.log_level == level.lower()


def test_settings_log_level_non_string_input_delegates_to_pydantic() -> None:
    """Non-string ``log_level`` input must surface as the standard Pydantic
    ``Literal`` error, not as a custom message from ``_normalize_log_level``.

    The validator's ``return value if not isinstance(value, str) else value.lower()``
    branch hands non-strings through unchanged so Pydantic's downstream
    type-coercion produces the canonical error. A future "improvement"
    that raises a custom error here would defeat the wire-shape principle
    that Pydantic validation is the source of error semantics.
    """
    with pytest.raises(ValidationError, match="Input should be 'debug'"):
        # ``42`` is the smallest non-string, non-tuple-of-Literal value
        # that exercises the ``isinstance(value, str)`` False branch.
        make_settings(log_level=42)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("invalid_host", ["", "x" * 254])
def test_settings_bind_host_field_constraints(
    invalid_host: str,
) -> None:
    """``bind_host`` rejects empty strings and 254+-char inputs at the field.

    The ``min_length=1`` / ``max_length=253`` Field constraints are belt-
    and-suspenders against the env-var path's ``env_ignore_empty=True``:
    a direct ``Settings(bind_host="")`` kwarg call (a malformed test
    fixture, an internal helper) bypasses the env-var-empty short-circuit
    and would otherwise reach ``_check_safety_invariants`` with an empty
    string, where ``is_private_host("")`` returns False → confusing
    "all-interfaces" error message. Pinning these bounds catches a future
    constraint drop.
    """
    with pytest.raises(ValidationError):
        make_settings(bind_host=invalid_host)


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("LIP_APP_ENV", "staging"),
        ("LIP_LOG_LEVEL", "trace"),
    ],
)
def test_settings_literal_field_rejects_unknown_value(
    monkeypatch: pytest.MonkeyPatch,
    var: str,
    value: str,
) -> None:
    """Literal-typed fields raise on values outside the declared enum.

    Critical for ``app_env`` because it gates ``/docs`` / ``/openapi.json``
    exposure; silent acceptance of an unknown value would default ``is_prod``
    to False and leak debug routes.
    """
    monkeypatch.setenv(var, value)
    with pytest.raises(ValidationError):
        make_settings()


# ── Bind-host clamp ──────────────────────────────────────────────────


@pytest.mark.parametrize("public_host", ["0.0.0.0", "::"])  # noqa: S104 — reject-list
def test_settings_bind_host_rejects_public_without_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
    public_host: str,
) -> None:
    """0.0.0.0 / :: bind without LIP_ALLOW_PUBLIC_BIND=true must raise.

    The clamp is the only barrier between a typo and an unauthenticated
    LLM proxy on the LAN. CLAUDE.md sacred rule #2 (TDD) — this validator
    branch was uncovered before.
    """
    monkeypatch.setenv("LIP_BIND_HOST", public_host)
    with pytest.raises(ValidationError, match="ALLOW_PUBLIC_BIND"):
        make_settings()


@pytest.mark.parametrize("public_host", ["0.0.0.0", "::"])  # noqa: S104 — reject-list
def test_settings_bind_host_accepts_public_with_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
    public_host: str,
) -> None:
    """LIP_ALLOW_PUBLIC_BIND=true unlocks the public-bind reject-list."""
    monkeypatch.setenv("LIP_BIND_HOST", public_host)
    monkeypatch.setenv("LIP_ALLOW_PUBLIC_BIND", "true")
    settings = make_settings()
    assert settings.bind_host == public_host


def test_settings_bind_host_accepts_loopback_default() -> None:
    """127.0.0.1 always succeeds — that is the safe default."""
    settings = make_settings()
    assert settings.bind_host == "127.0.0.1"


# ── Bind-port clamp ──────────────────────────────────────────────────


@pytest.mark.parametrize("port", [1023, 65536])
def test_settings_bind_port_rejects_out_of_range_values(
    monkeypatch: pytest.MonkeyPatch,
    port: int,
) -> None:
    """LIP_BIND_PORT outside [1024, 65535] must raise at validation time."""
    monkeypatch.setenv("LIP_BIND_PORT", str(port))
    with pytest.raises(ValidationError):
        make_settings()


@pytest.mark.parametrize("port", [1024, 8000, 65535])
def test_settings_bind_port_accepts_valid_values(
    monkeypatch: pytest.MonkeyPatch,
    port: int,
) -> None:
    """LIP_BIND_PORT inside [1024, 65535] must validate cleanly."""
    monkeypatch.setenv("LIP_BIND_PORT", str(port))
    settings = make_settings()
    assert settings.bind_port == port


# ── SSRF clamp ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "private_host",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://192.168.1.1:11434",
        "http://10.0.0.5:11434",
        "http://172.16.0.1:11434",
        "http://172.31.255.255:11434",
        "http://gemma.local:11434",
        # IPv6 bracketed positives — pin the AnyHttpUrl-strips-brackets contract
        # on the accept side too (negative-side IPv6 is already covered below).
        "http://[::1]:11434",
        "http://[fd00::1]:11434",
    ],
)
def test_settings_ollama_host_accepts_private_addresses(
    monkeypatch: pytest.MonkeyPatch,
    private_host: str,
) -> None:
    """Loopback / RFC1918 / mDNS hosts pass without opt-in."""
    monkeypatch.setenv("LIP_OLLAMA_HOST", private_host)
    settings = make_settings()
    # Verify the parsed URL preserves the host (rather than the
    # weaker ``is not None``: ``ollama_host`` is non-Optional with a
    # default, so a regression that stripped the SSRF allowlist and let
    # every host through silently passes ``is not None``).
    assert str(settings.ollama_host).startswith(private_host)


@pytest.mark.parametrize(
    "external_host",
    [
        "http://example.com:11434",
        "http://8.8.8.8:11434",
        "http://172.32.0.1:11434",  # outside the 172.16-31 RFC1918 range
        "http://[2606:4700:4700::1111]:11434",  # Cloudflare public IPv6
    ],
)
def test_settings_ollama_host_rejects_external_without_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
    external_host: str,
) -> None:
    """Non-private hosts must require LIP_ALLOW_EXTERNAL_OLLAMA=true."""
    monkeypatch.setenv("LIP_OLLAMA_HOST", external_host)
    with pytest.raises(ValidationError, match="ALLOW_EXTERNAL_OLLAMA"):
        make_settings()


def test_settings_ollama_host_accepts_external_with_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LIP_ALLOW_EXTERNAL_OLLAMA=true unlocks non-private hosts."""
    monkeypatch.setenv("LIP_OLLAMA_HOST", "http://example.com:11434")
    monkeypatch.setenv("LIP_ALLOW_EXTERNAL_OLLAMA", "true")
    settings = make_settings()
    assert settings.allow_external_ollama is True


@pytest.mark.parametrize(
    "userinfo_url",
    [
        "http://user@127.0.0.1:11434",
        "http://user:pass@127.0.0.1:11434",  # pragma: allowlist secret — test fixture
    ],
)
def test_settings_ollama_host_rejects_url_userinfo(
    monkeypatch: pytest.MonkeyPatch,
    userinfo_url: str,
) -> None:
    """``ollama_host`` URLs with embedded userinfo are rejected at Settings.

    The model_validator clamp at config.py:213-219 strips a vector where
    httpx exception strings (``ollama_call_failed`` log messages, error
    response bodies) could surface ``user:pass`` credentials. ``AnyHttpUrl``
    accepts userinfo by default; without this guard an operator who pastes
    a credentialed URL into ``LIP_OLLAMA_HOST`` would leak those creds at
    every connect failure.
    """
    monkeypatch.setenv("LIP_OLLAMA_HOST", userinfo_url)
    with pytest.raises(ValidationError, match="userinfo"):
        make_settings()


def test_is_private_host_classifier_covers_ipv6_and_ula() -> None:
    """The ipaddress-backed classifier catches IPv6 link-local + ULA cases.

    Note: ``ipaddress.is_private`` treats RFC 3849 documentation range
    (``2001:db8::/32``) as private, so we use a real public IPv6 (Cloudflare
    DNS ``2606:4700:4700::1111``) for the negative case.
    """
    assert is_private_host("127.0.0.1")
    assert is_private_host("::1")
    assert is_private_host("fe80::1")  # link-local
    assert is_private_host("fd00::1")  # ULA
    assert is_private_host("localhost")
    assert is_private_host("gemma.local")
    # IPv4-mapped IPv6 forms unwrap to their v4 classification — without
    # the ``ipv4_mapped`` re-classification in ``is_private_host`` an
    # operator who wrote the loopback as ``::ffff:127.0.0.1`` would fail
    # the SSRF clamp despite literally pointing at loopback.
    assert is_private_host("::ffff:127.0.0.1")
    assert is_private_host("::ffff:10.0.0.1")
    assert not is_private_host("::ffff:8.8.8.8")
    assert not is_private_host("8.8.8.8")
    assert not is_private_host("2606:4700:4700::1111")  # public IPv6
    assert not is_private_host("")


# ── lru_cache singleton ──────────────────────────────────────────────


def test_get_settings_returns_cached_singleton() -> None:
    """get_settings() must return the same instance — Depends() relies on it.

    No leading ``cache_clear()``: the autouse ``_reset_settings_cache``
    fixture in tests/conftest.py already clears the cache before every
    test, so a manual clear here would be dead defensive code.
    """
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_get_settings_cache_clear_invalidates_singleton() -> None:
    """``get_settings.cache_clear()`` produces a fresh instance on the next call.

    Locks the test-time escape hatch: the autouse
    ``_reset_settings_cache`` fixture in tests/conftest.py relies on this
    behavior to give each test a hermetic Settings instance. A future
    refactor that swaps lru_cache for a pre-construction-time singleton
    (without cache-clear semantics) would silently break the per-test
    isolation contract.
    """
    s1 = get_settings()
    get_settings.cache_clear()
    s2 = get_settings()
    assert s1 is not s2


def test_settings_model_validate_empty_dict_reads_lip_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Settings.model_validate({})`` runs the BaseSettings env-load path.

    ``app.api.deps.get_settings`` constructs Settings via
    ``Settings.model_validate({})`` (rather than ``Settings()``) to avoid
    a pyright false-positive on dynamic-init kwargs. The contract being
    relied on — that ``model_validate({})`` still consults the env loader —
    is a pydantic-settings 2.x behavior, not a Pydantic-core one. Pinning
    it here means a future Pydantic refactor that prioritizes the ``obj``
    argument over the env loader fails this test loudly instead of
    silently returning defaults.
    """
    monkeypatch.setenv("LIP_OLLAMA_HOST", "http://127.0.0.1:11500")
    monkeypatch.setenv("LIP_LOG_LEVEL", "warning")
    settings = Settings.model_validate({})
    assert str(settings.ollama_host) == "http://127.0.0.1:11500/"
    assert settings.log_level == "warning"
