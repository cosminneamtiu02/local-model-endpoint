"""Unit tests for Settings.ollama_host wiring (LIP-E003-F001 scenarios 7-8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import Settings

if TYPE_CHECKING:
    import pytest


def test_ollama_host_defaults_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """With OLLAMA_HOST unset, the default is the local Ollama port."""
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.ollama_host == "http://localhost:11434"


def test_ollama_host_env_var_overrides_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OLLAMA_HOST env var is reflected in Settings.ollama_host.

    pydantic-settings matches env vars case-insensitively by default,
    which is what makes the conventional UPPERCASE env var name map to
    the lowercase `ollama_host` field. Do not set `_case_sensitive=True`
    here — that would require the env var to be literally `ollama_host`,
    breaking the standard convention.
    """
    monkeypatch.setenv("OLLAMA_HOST", "http://192.168.1.50:11434")
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.ollama_host == "http://192.168.1.50:11434"
