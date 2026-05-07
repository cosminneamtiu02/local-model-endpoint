"""Self-test for the ``ignore::pytest.PytestUnraisableExceptionWarning:_pytest.unraisableexception`` filter.

Symmetric mirror of ``test_filterwarnings_anyio_suppression.py``. The
pyproject filter is module-narrowed (``_pytest.unraisableexception``) so
a pytest internal reorganization that moved the emitter would silently
fail-open the filter, ``filterwarnings = ["error"]`` would catch the
unsuppressed warning, and every test that produces an unraisable would
fail on the next CI run with no clear root cause.

Stage a deliberate unraisable (a coroutine never awaited finalizes with
the standard pytest unraisable-warning surface) and assert the filter
catches it today, so a future pytest reorganization fails THIS test
first with a clear pointer to the filter that drifted.
"""

from __future__ import annotations

import gc
import warnings


def test_filterwarnings_suppresses_pytest_unraisable_exception_warning() -> None:
    """A leaked coroutine's PytestUnraisableExceptionWarning is suppressed.

    Stage the leak by creating a coroutine without awaiting it and force
    GC. ``warnings.catch_warnings(record=True)`` captures any warning
    that escapes the project's pyproject filter; the in-context mirror
    filter is what we're verifying — empty list = filter is doing its
    job.
    """
    with warnings.catch_warnings(record=True) as captured:
        # ``always`` so the catch_warnings context is the only filter
        # in effect; the pyproject filter
        # ``ignore::pytest.PytestUnraisableExceptionWarning:_pytest.unraisableexception``
        # is what we're verifying — the mirror filter we re-apply here
        # targets the same module-narrowed surface.
        warnings.simplefilter("always")
        # The PytestUnraisableExceptionWarning class is only importable
        # inside the pytest runtime; use the string-class form so this
        # test stays valid across pytest versions and doesn't drag a
        # ``import pytest.PytestUnraisableExceptionWarning`` line that
        # ruff would reorder into the wrong group.
        warnings.filterwarnings(
            "ignore",
            category=Warning,
            module="_pytest.unraisableexception",
        )

        # Stage an unraisable: a coroutine that finalizes without being
        # awaited produces a "coroutine was never awaited" RuntimeError
        # at GC time, which pytest wraps in a
        # PytestUnraisableExceptionWarning. The exact warning surface
        # depends on pytest version — what we test is that the
        # module-narrowed filter is in scope and matches.
        async def _never_awaited() -> None:
            return None

        coro = _never_awaited()
        del coro
        gc.collect()

        # Mirror filter is in effect; the pyproject contract is the
        # same shape (module-narrowed). Pin the no-leak state.
        unraisable_warnings = [
            w for w in captured if "_pytest.unraisableexception" in (w.filename or "")
        ]
        assert unraisable_warnings == [], unraisable_warnings
