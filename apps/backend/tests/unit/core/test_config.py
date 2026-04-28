"""Unit tests for Settings.ollama_host wiring (LIP-E003-F001 scenarios 7-8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import Settings

if TYPE_CHECKING:
    import pytest


def test_ollama_host_defaults_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """With LIP_OLLAMA_HOST unset, the default is the local Ollama port."""
    monkeypatch.delenv("LIP_OLLAMA_HOST", raising=False)
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
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


def test_settings_is_frozen() -> None:
    """Settings is frozen — field assignment after construction must raise.

    The ``frozen=True`` invariant is load-bearing: the
    ``_check_safety_invariants`` model_validator runs only on construction,
    so allowing post-construction assignment would let a caller bypass the
    SSRF and public-bind clamps by mutating ``ollama_host`` or
    ``allow_public_bind`` after the fact.
    """
    assert Settings.model_config.get("frozen") is True
