"""Test factory for the Settings model.

Centralizes the ``_env_file=None`` test-isolation kwarg so individual
call sites in test_config.py don't each carry the magic kwarg
explicitly (and the docstring of ``make_settings`` documents why the
``model_validate`` form is preferred over the kwarg-spread form —
the mapping form passes pyright without any suppression at all).
"""

from app.core.config import Settings


def make_settings(**overrides: object) -> Settings:
    """Construct a Settings instance with dotenv loading disabled.

    Tests are expected to monkeypatch env vars via pytest-monkeypatch;
    this factory removes the need to remember ``_env_file=None`` on
    every call. The ``model_validate`` form is preferred over the
    kwarg-spread form because it avoids the ``reportCallIssue``
    cache-flap pyright emits on BaseSettings's untyped ``**values``
    route — no per-call-site suppression needed at all (the rationale
    block below documents this).
    """
    # ``model_validate`` accepts a typed ``Mapping`` (BaseSettings's
    # untyped ``**values`` route), so the magic ``_env_file`` kwarg
    # passes pyright without a suppression. Symmetric with the spread
    # form ``Settings(_env_file=None, **overrides)`` at runtime — the
    # mapping form is preferred because it avoids the
    # ``reportCallIssue`` cache-flap pyright emits on the kwarg-spread
    # form.
    return Settings.model_validate({"_env_file": None, **overrides})
