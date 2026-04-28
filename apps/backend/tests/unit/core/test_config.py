"""Unit tests for Settings.lip_ollama_host wiring (LIP-E003-F001 scenarios 7-8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import Settings

if TYPE_CHECKING:
    import pytest


def test_lip_ollama_host_defaults_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """With LIP_OLLAMA_HOST unset, the default is the local Ollama port."""
    monkeypatch.delenv("LIP_OLLAMA_HOST", raising=False)
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    # AnyHttpUrl normalizes to a trailing slash; compare via str().
    assert str(settings.lip_ollama_host) == "http://localhost:11434/"


def test_lip_ollama_host_env_var_overrides_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LIP_OLLAMA_HOST env var is reflected in Settings.lip_ollama_host.

    pydantic-settings matches env vars case-insensitively by default,
    which is what makes the conventional UPPERCASE env var name map to
    the lowercase `lip_ollama_host` field. Do not set
    `_case_sensitive=True` here — that would require the env var to be
    literally `lip_ollama_host`, breaking the standard convention.

    The override host must be in the SSRF-clamp allowlist (loopback /
    RFC1918 / link-local) — `127.0.0.1` is the simplest legal value.
    """
    monkeypatch.setenv("LIP_OLLAMA_HOST", "http://127.0.0.1:11500")
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert str(settings.lip_ollama_host) == "http://127.0.0.1:11500/"
