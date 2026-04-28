"""Top-level test fixtures for the error-contracts package."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Match ``class Test<word>`` at column 0. Catches both plain
# ``class TestFoo:`` and ``class TestFoo(unittest.TestCase):`` forms.
_TEST_CLASS_PATTERN = re.compile(r"^class Test[A-Za-z_]", re.MULTILINE)


def pytest_sessionstart(session: pytest.Session) -> None:
    """Mechanically enforce CLAUDE.md sacred rule: no test classes.

    ``pyproject.toml`` sets ``python_classes = ["NoTestClassesAllowed"]`` to
    suppress *discovery* of methods inside class-based test containers. That
    suppression is silent: a contributor adding ``class TestFoo:`` with
    ``def test_bar(self)`` methods sees green CI with zero coverage of those
    assertions. This session-start scan reads every ``test_*.py`` under the
    conftest's directory tree and fails the session loudly if any
    ``^class Test...`` definition is found, converting the silent-uncollection
    footgun into a hard failure at session start.

    Mirrors the identical hook in ``apps/backend/tests/conftest.py`` so both
    test trees enforce the same sacred rule mechanically.
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
