"""Test factory for the Settings model.

Centralizes the ``_env_file=None`` test-isolation kwarg so individual
call sites in test_config.py don't each carry the magic kwarg
explicitly. The ``model_validate`` form is preferred over the
kwarg-spread form because it avoids the ``reportCallIssue`` cache-flap
pyright emits on BaseSettings's untyped ``**values`` route — no
per-call-site suppression needed at all.
"""

from app.core.config import Settings


def make_settings(**overrides: object) -> Settings:
    """Construct a Settings instance with dotenv loading disabled.

    See module docstring for the ``model_validate``-vs-spread rationale.
    """
    return Settings.model_validate({"_env_file": None, **overrides})
