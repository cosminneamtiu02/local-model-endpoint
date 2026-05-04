"""Test factory for the Settings model.

Centralizes the ``_env_file=None`` test-isolation kwarg + the
pyright-suppression so the 12 individual call sites in test_config.py
don't each carry a ``# pyright: ignore`` comment.
"""

from __future__ import annotations

from app.core.config import Settings


def make_settings(**overrides: object) -> Settings:
    """Construct a Settings instance with dotenv loading disabled.

    Tests are expected to monkeypatch env vars via pytest-monkeypatch;
    this factory removes the need to remember _env_file=None on every call
    and centralizes the BaseSettings init pyright-suppression.
    """
    return Settings(_env_file=None, **overrides)  # pyright: ignore[reportCallIssue]  # BaseSettings init not visible to pyright
