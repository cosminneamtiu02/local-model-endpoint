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
    # ``model_validate`` accepts a typed ``Mapping`` (BaseSettings's
    # untyped ``**values`` route), so the magic ``_env_file`` kwarg
    # passes pyright without a suppression. Symmetric with the spread
    # form ``Settings(_env_file=None, **overrides)`` at runtime — the
    # mapping form is preferred because it avoids the
    # ``reportCallIssue`` cache-flap pyright emits on the kwarg-spread
    # form (see lane-3.1 round-18 fix discussion).
    return Settings.model_validate({"_env_file": None, **overrides})
