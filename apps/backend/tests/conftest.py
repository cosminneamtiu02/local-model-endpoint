"""Top-level test fixtures."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import structlog

if TYPE_CHECKING:
    from collections.abc import Iterator

# Match ``class Test<word>`` at column 0. Catches both plain
# ``class TestFoo:`` and ``class TestFoo(unittest.TestCase):`` forms;
# does NOT catch ``class _TestFoo:`` (leading underscore is private
# convention, and pytest skips them anyway under the ``Test`` prefix
# rule). MUST stay in lockstep with the same regex in
# ``packages/error-contracts/tests/conftest.py``; cross-workspace import
# isn't installable so the duplication is intentional and the cross-
# reference comment is the only enforcement.
_TEST_CLASS_PATTERN = re.compile(r"^class Test[A-Za-z_]", re.MULTILINE)


def pytest_sessionstart(session: pytest.Session) -> None:  # noqa: ARG001 — name fixed by pytest hookspec
    """Mechanically enforce CLAUDE.md sacred rule: no test classes.

    ``pyproject.toml`` sets ``python_classes = ["NoTestClassesAllowed"]`` to
    suppress *discovery* of methods inside class-based test containers. That
    suppression is silent: a contributor adding ``class TestFoo:`` with
    ``def test_bar(self)`` methods sees green CI with zero coverage of those
    assertions. This session-start scan reads every ``test_*.py`` under the
    conftest's directory tree and fails the session loudly if any
    ``^class Test...`` definition is found, converting the silent-uncollection
    footgun into a hard failure at session start.

    Catches ``unittest.TestCase`` subclasses too via the same regex
    (``class TestFoo(unittest.TestCase):`` matches at column 0). Pytest
    discovers ``unittest.TestCase`` subclasses regardless of ``python_classes``
    — so this scan is the only mechanism that fires before any collection
    work, allowing the failure to be attributed to the file rather than to
    a downstream collection error.
    """
    test_root = Path(__file__).parent
    offenders: list[str] = []
    for py_file in test_root.rglob("test_*.py"):
        content = py_file.read_text(encoding="utf-8")
        for match in _TEST_CLASS_PATTERN.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            offenders.append(f"{py_file.relative_to(test_root.parent)}:{line_no}")
    if offenders:
        joined = "\n  - ".join(offenders)
        msg = (
            "CLAUDE.md sacred rule violated: no test classes "
            "(see Forbidden Patterns — Cross-cutting). "
            f"Found {len(offenders)} class definition(s) in test files:\n  - "
            f"{joined}\n"
            "Convert to module-level pytest functions "
            "(`def test_foo() -> None:`)."
        )
        pytest.exit(msg, returncode=2)


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Reset get_settings's lru_cache around every test."""
    from app.api.deps import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_structlog_contextvars() -> Iterator[None]:
    """Clear structlog contextvars between tests.

    structlog.reset_defaults() (used elsewhere) resets configuration only,
    not the per-task contextvars dict. Without this clear, a test that binds
    request_id / error_code via structlog.contextvars.bind_contextvars
    leaves stale keys for the next test in the same worker. Promoted to
    project-wide so non-logging tests inherit the isolation.
    """
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ``LIP_*`` env vars so tests see only what they explicitly set.

    Promoted from ``tests/unit/core/conftest.py`` to the root so integration
    tests + the future contract suite also get hermetic Settings construction.
    The unit/core scope was insufficient: a developer with ``LIP_APP_ENV=
    production`` in their shell would silently flip ``is_prod`` for every
    integration test that imports ``app.main.app``. Reading the prefix +
    field-name set at import time means a new Settings field is auto-
    covered — no per-test edit needed.

    Case-fold-symmetric with ``Settings.model_config["case_sensitive"]=False``:
    pydantic-settings folds ``lip_app_env=production`` onto the ``app_env``
    field, but ``monkeypatch.delenv("LIP_APP_ENV")`` would not strip the
    lowercase form, so a developer with ``lip_app_env=production`` in
    their shell would still silently flip ``is_prod``. We iterate
    ``os.environ`` once and drop every name whose ``.upper()`` starts
    with the prefix — subsumes the upper-only delete in one pass.
    """
    import os

    from app.core.config import Settings

    env_prefix = Settings.model_config.get("env_prefix") or ""
    if not env_prefix:
        # Defensive guard mirroring ``audit_lip_env_typos``: an empty
        # prefix would match every env var on the host.
        return
    env_prefix_upper = env_prefix.upper()
    for name in [n for n in os.environ if n.upper().startswith(env_prefix_upper)]:
        monkeypatch.delenv(name, raising=False)
