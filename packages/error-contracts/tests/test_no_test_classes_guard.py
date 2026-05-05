"""Self-tests for the error-contracts ``pytest_sessionstart`` no-classes regex.

Mirror of ``apps/backend/tests/unit/test_no_test_classes_guard.py``. The
backend's self-test only exercises the apps/backend conftest's
``_TEST_CLASS_PATTERN``. The same regex is duplicated (intentionally —
cross-workspace import isn't installable) in
``packages/error-contracts/tests/conftest.py``; the
``check:test-class-regex-sync`` Taskfile target only does a textual grep
equality on the literal ``re.compile(...)`` source line, so two regex
strings that LOOK identical but parse to different behaviors (e.g. via
non-printing whitespace, or via deliberately compiling different flags
in a future edit) would pass that gate.

This self-test parametrizes the SAME 10 documented behaviors as the
backend self-test against the packages-side regex object. Together with
the backend self-test, it converts the textual-equality gate into a
behavior-equality gate.
"""

from __future__ import annotations

import pytest

from tests.conftest import _TEST_CLASS_PATTERN  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    "source",
    [
        "class TestFoo:\n    pass",
        "class TestFoo(unittest.TestCase):\n    pass",
        "class TestBar:\n    def test_x(self): ...",
        "class Test_Bar:\n    pass",
    ],
)
def test_no_classes_guard_matches_offending_class(source: str) -> None:
    """Every flavor of ``class Test...`` at column 0 must match the regex."""
    assert _TEST_CLASS_PATTERN.search(source) is not None


def test_no_classes_guard_documents_digit_after_test_is_not_matched() -> None:
    """``class Test1:`` does NOT match — same contract as the backend regex."""
    assert _TEST_CLASS_PATTERN.search("class Test1:\n    pass") is None


@pytest.mark.parametrize(
    "source",
    [
        "class _TestFoo:\n    pass",
        "class testfoo:\n    pass",
        "    class TestFoo:\n        pass",
        "class Foo:\n    pass",
        "def test_foo() -> None:\n    pass",
    ],
)
def test_no_classes_guard_rejects_non_offending_source(source: str) -> None:
    """Non-class-based test source must NOT match the regex."""
    assert _TEST_CLASS_PATTERN.search(source) is None
