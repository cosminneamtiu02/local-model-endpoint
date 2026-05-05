"""Drift guard between codegen and wire schema for the SCREAMING_SNAKE regex.

The codegen validates ``errors.yaml`` codes with a SCREAMING_SNAKE regex,
and ``ProblemDetails.code`` (the wire schema) declares the SAME regex as
defense-in-depth — a future drift would let a code that the codegen
accepts fail the wire schema at request time as a 500. The two sources
live in separate workspaces and cannot share imports (mirrors the
``test_problem_extras_drift_guard`` situation), so the contract is
enforced by hand-sync. This test backstops the hand-sync.
"""

import importlib.util
import sys
from pathlib import Path

from app.schemas import ProblemDetails


def _load_codegen_screaming_snake_pattern() -> str:
    """Load ``_SCREAMING_SNAKE_CODE_PATTERN.pattern`` from the codegen.

    Same recipe as ``test_problem_extras_drift_guard._load_codegen_reserved_param_names``:
    the error-contracts script is loaded by file path because importing
    through the package surface would require an editable install into
    the backend venv. Returns the raw regex string so the test can
    string-compare against the wire schema's pattern.
    """
    repo_root = Path(__file__).resolve().parents[5]
    generate_py = repo_root / "packages" / "error-contracts" / "scripts" / "generate.py"
    spec = importlib.util.spec_from_file_location(
        "_drift_guard_generate_pattern",
        generate_py,
    )
    assert spec is not None, generate_py
    assert spec.loader is not None, generate_py
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_drift_guard_generate_pattern", module)
    spec.loader.exec_module(module)
    pattern: str = module._SCREAMING_SNAKE_CODE_PATTERN.pattern
    return pattern


def test_screaming_snake_pattern_is_identical_across_codegen_and_wire_schema() -> None:
    """The codegen's code-validation regex must equal the wire schema's.

    Adding/relaxing one without the other lets a codegen-accepted YAML
    code fail the wire schema at request time (or vice versa, a relaxed
    wire schema accepts codes the codegen would never produce).
    """
    codegen_pattern = _load_codegen_screaming_snake_pattern()
    wire_pattern_meta = ProblemDetails.model_fields["code"].metadata
    # Pydantic v2 stores the ``pattern`` constraint on the field as a
    # ``Pattern`` metadata entry; pull the regex source string off it.
    wire_pattern = next(
        getattr(m, "pattern", None) for m in wire_pattern_meta if getattr(m, "pattern", None)
    )
    assert codegen_pattern == wire_pattern, (
        f"SCREAMING_SNAKE regex drifted: codegen={codegen_pattern!r} vs "
        f"ProblemDetails.code pattern={wire_pattern!r}"
    )
