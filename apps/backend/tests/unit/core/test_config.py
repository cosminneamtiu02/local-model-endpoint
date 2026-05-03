"""Unit tests for Settings (LIP-E003-F001 + safety-clamp coverage)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.deps import get_settings
from app.core.config import Settings, is_private_host


def test_ollama_host_defaults_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """With LIP_OLLAMA_HOST unset, the default is the local Ollama port."""
    monkeypatch.delenv("LIP_OLLAMA_HOST", raising=False)
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]  # BaseSettings init not visible to pyright
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
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert str(settings.ollama_host) == "http://127.0.0.1:11500/"


def test_settings_is_frozen_at_runtime() -> None:
    """Settings is frozen — field assignment after construction must raise.

    The ``frozen=True`` invariant is load-bearing: the
    ``_check_safety_invariants`` model_validator runs only on construction,
    so allowing post-construction assignment would let a caller bypass the
    SSRF and public-bind clamps by mutating ``ollama_host`` or
    ``allow_public_bind`` after the fact. Asserting the BEHAVIOR (assignment
    raises) instead of the FLAG (model_config["frozen"] is True) catches
    both flag drift AND a future pydantic-settings change to what
    ``frozen=True`` means.
    """
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValidationError):
        settings.allow_public_bind = True  # type: ignore[misc]


def test_settings_extra_forbid_rejects_unknown_kwarg() -> None:
    """extra='forbid' rejects unknown init kwargs (the kwarg-equivalent surface)."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, bogus_field="x")  # pyright: ignore[reportCallIssue]


def test_settings_extra_forbid_silently_ignores_unknown_env_var() -> None:
    """extra='forbid' is enforced on init kwargs ONLY — env vars are silent.

    pydantic-settings 2.14 explicitly does NOT honor ``extra='forbid'`` for
    env-var sources. A typo like ``LIP_OLLMA_HOST=...`` in .env is silently
    ignored rather than raising at import time. Pinning this surprise so the
    cache files / future docs cannot drift back to claiming env-var rejection.
    """
    import os

    os.environ["LIP_BOGUS_ENV_VAR"] = "x"
    try:
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]  # must not raise
    finally:
        del os.environ["LIP_BOGUS_ENV_VAR"]


def test_settings_case_sensitive_default_off() -> None:
    """case_sensitive is the pydantic-settings default; pin it so a future
    upstream default flip surfaces here instead of silently breaking
    lowercase env vars in .env files."""
    assert Settings.model_config.get("case_sensitive") is False


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
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


# ── Bind-host clamp (Lane 19.9) ──────────────────────────────────────


@pytest.mark.parametrize("public_host", ["0.0.0.0", "::"])  # noqa: S104 - reject-list
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
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("public_host", ["0.0.0.0", "::"])  # noqa: S104
def test_settings_bind_host_accepts_public_with_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
    public_host: str,
) -> None:
    """LIP_ALLOW_PUBLIC_BIND=true unlocks the public-bind reject-list."""
    monkeypatch.setenv("LIP_BIND_HOST", public_host)
    monkeypatch.setenv("LIP_ALLOW_PUBLIC_BIND", "true")
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.bind_host == public_host


def test_settings_bind_host_accepts_loopback_default() -> None:
    """127.0.0.1 always succeeds — that is the safe default."""
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.bind_host == "127.0.0.1"


# ── SSRF clamp (Lane 19.10) ──────────────────────────────────────────


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
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.ollama_host is not None


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
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_settings_ollama_host_accepts_external_with_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LIP_ALLOW_EXTERNAL_OLLAMA=true unlocks non-private hosts."""
    monkeypatch.setenv("LIP_OLLAMA_HOST", "http://example.com:11434")
    monkeypatch.setenv("LIP_ALLOW_EXTERNAL_OLLAMA", "true")
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.allow_external_ollama is True


def testis_private_host_classifier_covers_ipv6_and_ula() -> None:
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
    assert not is_private_host("8.8.8.8")
    assert not is_private_host("2606:4700:4700::1111")  # public IPv6
    assert not is_private_host("")


# ── lru_cache singleton (Lane 19.6) ──────────────────────────────────


def test_get_settings_returns_cached_singleton() -> None:
    """get_settings() must return the same instance — Depends() relies on it.

    No leading ``cache_clear()``: the autouse ``_reset_settings_cache``
    fixture in tests/conftest.py already clears the cache before every
    test, so a manual clear here would be dead defensive code.
    """
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
