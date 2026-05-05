"""Test factory for the Settings model.

Centralizes the ``_env_file=None`` test-isolation kwarg + the
pyright-suppression so the 12 individual call sites in test_config.py
don't each carry a ``# pyright: ignore`` comment.
"""

from app.core.config import Settings


def make_settings(**overrides: object) -> Settings:
    """Construct a Settings instance with dotenv loading disabled.

    Tests are expected to monkeypatch env vars via pytest-monkeypatch;
    this factory removes the need to remember _env_file=None on every call
    and centralizes the BaseSettings init pyright-suppression.
    """
    # ``# pyright: ignore[reportCallIssue]`` — pyright cannot reconcile
    # ``**overrides: object`` against the BaseSettings typed init kwargs
    # (``_env_file: PathType | None``, ``_env_file_encoding: str | None``,
    # plus per-field aliases). Settings has no aliased fields today; if any
    # land, prefer ``Settings.model_validate({"_env_file": None, **overrides})``
    # over kwarg-spread so the call site stays typed without the ignore.
    return Settings(_env_file=None, **overrides)  # pyright: ignore[reportCallIssue]
