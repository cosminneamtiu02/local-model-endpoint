"""Pin the set of hand-written files under ``app/exceptions/``.

CLAUDE.md "Forbidden Patterns" forbids editing files in
``app/exceptions/_generated/``; the codegen + ``task check:errors`` pipeline
catches drift inside that subtree. This test pins the COMPLEMENTARY
invariant: only ``base.py`` and ``__init__.py`` are hand-written under
``app/exceptions/``. A future contributor adding a sibling
``app/exceptions/utils.py`` (or any other hand-written file) widens the
DomainError seam beyond what ``errors.yaml`` controls — silently, because
``check:errors`` only diffs the ``_generated/`` tree.

Adding a new hand-written file requires both updating this test AND adding
an ADR explaining why the new surface needs to live outside ``errors.yaml``.
"""

from pathlib import Path

# Locked here so a future move of the exceptions/ package surfaces as one
# constant edit rather than scattered hardcoded paths.
_EXCEPTIONS_DIR = Path(__file__).parents[3] / "app" / "exceptions"

# The exact set of allowed entries directly under ``app/exceptions/``.
# Both files (``__init__.py``, ``base.py``) and one subdirectory
# (``_generated/``) are the entire load-bearing hand-written surface.
# ``__pycache__`` is a runtime artifact, filtered explicitly so the
# assertion stays deterministic across cold/warm test runs.
_ALLOWED_EXCEPTIONS_ENTRIES = frozenset({"__init__.py", "base.py", "_generated"})


def test_exceptions_dir_contains_only_allowed_entries() -> None:
    """Pin the file-set discipline of ``app/exceptions/``.

    Mechanically enforces the "only base.py is hand-written; everything
    else lives in errors.yaml" rule. A new entry under this directory
    means either a new generated file (handled by the codegen pipeline)
    or a new hand-written file (which needs an ADR + a test update here).
    """
    actual = {entry.name for entry in _EXCEPTIONS_DIR.iterdir() if entry.name != "__pycache__"}
    assert actual == _ALLOWED_EXCEPTIONS_ENTRIES, (
        f"Unexpected entries under app/exceptions/: {actual - _ALLOWED_EXCEPTIONS_ENTRIES}. "
        f"Missing: {_ALLOWED_EXCEPTIONS_ENTRIES - actual}. "
        "Adding a hand-written sibling to base.py requires an ADR explaining "
        "why the new surface needs to live outside errors.yaml — see CLAUDE.md "
        "Error System discipline."
    )
