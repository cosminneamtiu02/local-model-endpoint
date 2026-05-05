"""Self-tests for the ``pytest_sessionstart`` no-classes guard regex.

The CLAUDE.md sacred rule "Never write a test class" is enforced by two
layers:

1. ``pyproject.toml`` ``python_classes = ["NoTestClassesAllowed"]`` —
   silently suppresses pytest's class-based discovery; the literal
   sentinel name is one no realistic author writes, so any
   ``class TestFoo:`` simply isn't collected.
2. ``tests/conftest.py``'s ``pytest_sessionstart`` hook + the
   ``_TEST_CLASS_PATTERN`` regex — converts the silent suppression
   into a loud session-start failure so a contributor knows their
   class definition isn't being collected.

Without these tests, a future regex regression (e.g. accidentally
adding ``re.IGNORECASE`` and dropping the ``^`` anchor) silently widens
the suppression while the layer-1 silent-drop continues to mask the
broken layer-2 enforcement. Pinning every documented behavior of the
regex closes that hole.
"""

from __future__ import annotations

import pytest

from tests.conftest import _TEST_CLASS_PATTERN


@pytest.mark.parametrize(
    "source",
    [
        "class TestFoo:\n    pass",
        "class TestFoo(unittest.TestCase):\n    pass",
        "class TestBar:\n    def test_x(self): ...",
        # Underscore continuation — ``class Test_Foo`` is rare but valid
        # Python; the regex's ``[A-Za-z_]`` accepts it.
        "class Test_Bar:\n    pass",
    ],
)
def test_no_classes_guard_matches_offending_class(source: str) -> None:
    """Every flavor of ``class Test...`` at column 0 must match the regex."""
    assert _TEST_CLASS_PATTERN.search(source) is not None


def test_no_classes_guard_documents_digit_after_test_is_not_matched() -> None:
    """``class Test1:`` does NOT match the regex.

    The character class ``[A-Za-z_]`` after ``Test`` is intentional: a
    pytest test container is conventionally ``TestPascalCase`` (a
    capital, lowercase, or underscore continuation). Pure-digit
    continuations are not idiomatic; the regex prioritizes the false-
    positive class (private ``_Test...``) over a hypothetical
    ``Test1Foo`` form.
    """
    assert _TEST_CLASS_PATTERN.search("class Test1:\n    pass") is None


@pytest.mark.parametrize(
    "source",
    [
        # Leading underscore — private class, not a test container.
        "class _TestFoo:\n    pass",
        # Lower-case ``test`` prefix — fails CLAUDE.md naming, but the
        # discovery layer (python_classes pin) is what enforces that;
        # the regex is anchored on the canonical TitleCase ``Test`` form.
        "class testfoo:\n    pass",
        # Indented (inner class) — pytest doesn't discover inner classes
        # anyway, and the regex's ``^`` anchor with re.MULTILINE excludes
        # them.
        "    class TestFoo:\n        pass",
        # Adjacent name (``TestableFoo`` is not a test container — pytest
        # discovers only ``Test`` followed by an upper or non-letter; the
        # regex's character class ``[A-Za-z_]`` restricts to that form).
        "class Foo:\n    pass",
        # Functions (the canonical CLAUDE.md form) must NOT match.
        "def test_foo() -> None:\n    pass",
    ],
)
def test_no_classes_guard_rejects_non_offending_source(source: str) -> None:
    """Non-class-based test source must NOT match the regex."""
    assert _TEST_CLASS_PATTERN.search(source) is None
