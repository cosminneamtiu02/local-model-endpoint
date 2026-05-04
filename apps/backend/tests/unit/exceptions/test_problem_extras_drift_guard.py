"""Drift guard between ``ProblemExtras`` (wire schema) and the codegen's
``RESERVED_PARAM_NAMES`` (codegen-time forbidden YAML param names).

The codegen forbids YAML-declared params from colliding with seven RFC 7807
keys plus every ``ProblemExtras`` field name. The two sources cannot import
each other (cross-workspace), so the contract is enforced by hand-sync.
This test pins the contract: every ``ProblemExtras`` field MUST be in the
codegen's reserved set, otherwise a YAML param could shadow a typed-extension
key on the wire and trip ``_build_problem_payload``'s collision detector at
request time as a 500.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app.schemas import ProblemExtras


def _load_codegen_reserved_param_names() -> frozenset[str]:
    """Load ``RESERVED_PARAM_NAMES`` from the error-contracts codegen.

    The error-contracts package is a sibling workspace; importing through the
    package surface would require an editable install of error-contracts into
    the backend venv. Instead, load the script module by file path so the
    codegen's source-of-truth set is read directly without rewiring the
    install layout.
    """
    repo_root = Path(__file__).resolve().parents[5]
    generate_py = repo_root / "packages" / "error-contracts" / "scripts" / "generate.py"
    spec = importlib.util.spec_from_file_location("_drift_guard_generate", generate_py)
    assert spec is not None, generate_py
    assert spec.loader is not None, generate_py
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_drift_guard_generate", module)
    spec.loader.exec_module(module)
    return module.RESERVED_PARAM_NAMES


def test_problem_extras_field_names_are_reserved_in_codegen() -> None:
    """Every ProblemExtras field name MUST be in the codegen's RESERVED_PARAM_NAMES.

    Adding a new ProblemExtras key without adding it to the codegen set lets a
    YAML param of the same name silently shadow the extension on the wire.
    The runtime collision detector catches this as a 500, but only after the
    bug ships — this test catches it at CI time.
    """
    extras_fields = set(ProblemExtras.model_fields.keys())
    reserved = _load_codegen_reserved_param_names()
    missing = extras_fields - reserved
    assert not missing, (
        f"ProblemExtras fields {sorted(missing)} are not in codegen "
        f"RESERVED_PARAM_NAMES; add them to packages/error-contracts/scripts/"
        f"generate.py:RESERVED_PARAM_NAMES so YAML params cannot collide."
    )


def test_rfc7807_envelope_field_names_are_reserved_in_codegen() -> None:
    """The seven RFC 7807 + LIP envelope keys MUST be in RESERVED_PARAM_NAMES.

    The codegen and the runtime ``_build_problem_payload`` both spread params
    at the root of the wire body. A YAML-declared param named ``status`` /
    ``instance`` / ``code`` would shadow the envelope kwarg on the
    ``ProblemDetails(...)`` call and either ship a confusing wire body or
    trip the handler's collision detector as a 500. The test backstops the
    envelope side of the contract — siblings to the
    ``test_problem_extras_field_names_are_reserved_in_codegen`` extension
    side — so a future renamed envelope field stays in sync with the
    codegen reservation.
    """
    rfc7807_envelope_fields = frozenset(
        {
            "type",
            "title",
            "status",
            "detail",
            "instance",
            "code",
            "request_id",
        }
    )
    reserved = _load_codegen_reserved_param_names()
    missing = rfc7807_envelope_fields - reserved
    assert not missing, (
        f"RFC 7807 envelope fields {sorted(missing)} are not in codegen "
        f"RESERVED_PARAM_NAMES; rename in lockstep with "
        f"packages/error-contracts/scripts/generate.py and "
        f"app/api/exception_handlers._build_problem_payload."
    )
