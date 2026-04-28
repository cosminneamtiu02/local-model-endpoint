"""Hermetic-config fixture — strips Settings env vars before each unit test.

Prevents CI runners or developer shells with stray env vars (e.g.
LOG_LEVEL, BIND_PORT) from polluting Settings()-construction tests in
this package. Each Settings field name is delenv'd via monkeypatch so
the reset is automatically rolled back at end of test.
"""

import pytest

_SETTINGS_ENV_VARS = (
    "APP_ENV",
    "LOG_LEVEL",
    "LIP_OLLAMA_HOST",
    "BIND_HOST",
    "BIND_PORT",
    "ALLOW_PUBLIC_BIND",
)


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove Settings env vars so tests see only what they explicitly set."""
    for var in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
