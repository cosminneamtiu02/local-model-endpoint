"""Drift guard between ``ProblemDetails.title`` (wire schema) and the codegen's
``_TITLE_MAX_CHARS`` (codegen-time YAML title cap).

The two literals must agree: a YAML title accepted by codegen but rejected
by the wire schema would silently demote the typed error to InternalError
in the catch-all 500 path. Cross-workspace: the codegen module is loaded
by file path (mirror of ``test_problem_extras_drift_guard.py``).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# ``_TITLE_MAX_CHARS`` is module-private to ``problem_details.py``; tests
# treat it as a load-bearing constant per the existing drift-guard
# discipline (see also ``_DESCRIPTION_MAX_CHARS`` which the codegen
# unilaterally pins). Reading it via the module attribute keeps this test
# automatically in sync with any future renamings.
from app.schemas import problem_details as _wire_problem_details


def _load_codegen_title_max_chars() -> int:
    """Load ``_TITLE_MAX_CHARS`` from the error-contracts codegen by file path.

    Same loader pattern as ``test_problem_extras_drift_guard.py`` —
    cross-workspace import without an editable install of error-contracts
    into the backend venv.
    """
    repo_root = Path(__file__).resolve().parents[5]
    generate_py = repo_root / "packages" / "error-contracts" / "scripts" / "generate.py"
    spec = importlib.util.spec_from_file_location("_drift_guard_title_cap", generate_py)
    assert spec is not None, generate_py
    assert spec.loader is not None, generate_py
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_drift_guard_title_cap", module)
    spec.loader.exec_module(module)
    return module._TITLE_MAX_CHARS


def test_title_max_chars_codegen_matches_wire_schema() -> None:
    """``_TITLE_MAX_CHARS`` in the codegen MUST equal the wire-schema cap.

    A divergence means the codegen accepts YAML titles the wire schema
    rejects (cap reduced wire-side) or accepts at the wire what codegen
    rejects (cap reduced codegen-side). Either way the typed error
    surface is silently degraded — codegen-side rejection turns into a
    500 (the load-bearing case), wire-side rejection ships a working
    typed error that fails on construction at request time.
    """
    codegen_cap = _load_codegen_title_max_chars()
    wire_cap = _wire_problem_details._TITLE_MAX_CHARS
    assert codegen_cap == wire_cap, (
        f"Title-cap drift: codegen has _TITLE_MAX_CHARS={codegen_cap}, "
        f"ProblemDetails wire schema has _TITLE_MAX_CHARS={wire_cap}. "
        "Update both in lockstep at "
        "packages/error-contracts/scripts/generate.py and "
        "apps/backend/app/schemas/problem_details.py."
    )
