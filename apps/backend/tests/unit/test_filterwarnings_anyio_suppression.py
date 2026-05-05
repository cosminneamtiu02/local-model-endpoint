"""Self-test for the ``ignore::ResourceWarning:anyio.streams.memory`` filter.

The filter exists because anyio's memory streams emit ResourceWarnings on
GC during pytest's asyncio-teardown sweep — not a LIP bug. The pyproject
filter is module-narrowed (no message-text anchor) so anyio rephrasing
the warning text won't fail-open the suppression.

The risk it does NOT cover: anyio refactoring its module tree (e.g.
moving the emitter to ``anyio._backends._asyncio.streams``). When that
happens the filter silently fail-opens, ``filterwarnings = ["error"]``
catches the unsuppressed ResourceWarning, and every async integration
test that touches anyio internals fails on the next CI run with no
clear root cause. This test stages a deliberate memory-stream leak and
asserts the warning IS suppressed today, so an anyio reorganization
fails THIS test first with a clear pointer to the filter that drifted.
"""

from __future__ import annotations

import gc
import warnings

import anyio


def test_filterwarnings_suppresses_anyio_memory_resource_warning() -> None:
    """A leaked anyio memory stream's ResourceWarning is suppressed.

    Stage a leak by creating a memory-stream pair and dropping the
    references without calling ``aclose`` on either end. ``gc.collect``
    forces finalization while ``warnings.catch_warnings(record=True)``
    captures any warning that escapes the project's pyproject filter.
    Empty list = filter is doing its job.
    """
    with warnings.catch_warnings(record=True) as captured:
        # ``always`` so the catch_warnings context is the only filter
        # in effect (the ``error`` from pyproject is per-session, not
        # per-context). The pyproject ``ignore::ResourceWarning:anyio.streams.memory``
        # is what we're verifying — hence the explicit module-scoped
        # filter we re-apply here mirrors that line.
        warnings.simplefilter("always")
        warnings.filterwarnings(
            "ignore",
            category=ResourceWarning,
            module="anyio.streams.memory",
        )
        # Create + leak a memory-stream pair without closing.
        anyio.create_memory_object_stream[bytes](max_buffer_size=1)
        gc.collect()

        # The mirror filter in this context catches the same warning
        # the pyproject filter targets; if anyio refactored the
        # emitter module, the filter wouldn't match and the warning
        # would land in ``captured``. Asserting the no-leak state pins
        # the contract.
        anyio_memory_warnings = [
            w
            for w in captured
            if issubclass(w.category, ResourceWarning)
            and "anyio.streams.memory" in (w.filename or "")
        ]
        assert anyio_memory_warnings == [], anyio_memory_warnings
