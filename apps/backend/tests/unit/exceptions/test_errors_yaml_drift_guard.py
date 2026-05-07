"""Source-of-truth invariants for packages/error-contracts/errors.yaml.

The codegen pipeline runs YAML → load_and_validate → file emission →
``task check:errors`` (which diffs the generated tree). That gate
catches drift between checked-in generated files and YAML, but does NOT
catch a regression where the YAML itself is structurally wrong (zero
codes, wrong version) — the generator would silently produce an empty
``_generated/`` tree and pass the diff check on a green-but-empty state.

These tests pin the structural floor: the YAML must declare
``version: 1`` and at least the baseline of 10 codes; every code must
carry a non-empty description and an HTTP status in the 400-599 range.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# The canonical source-of-truth path — locked here so a future move of
# errors.yaml requires updating one constant rather than every test.
_ERRORS_YAML_PATH = Path(__file__).parents[5] / "packages" / "error-contracts" / "errors.yaml"

# Baseline floor. A future code addition is permitted (assert with >=);
# a code removal is a wire-contract change that must come with an
# explicit test update + ADR. Tracking the exact baseline catches both
# silent removals AND an "I generated zero codes" regression at once.
# Bumped to 11 after METHOD_NOT_ALLOWED landed: 5 generic codes
# (NOT_FOUND, METHOD_NOT_ALLOWED, CONFLICT, INTERNAL_ERROR,
# VALIDATION_FAILED) + 6 LIP-specific codes (RATE_LIMITED, QUEUE_FULL,
# INFERENCE_TIMEOUT, MODEL_CAPABILITY_NOT_SUPPORTED, REGISTRY_NOT_FOUND,
# ADAPTER_CONNECTION_FAILURE). Bump in lockstep with errors.yaml additions.
_MIN_CODE_COUNT = 11


@pytest.fixture(scope="module")
def errors_data() -> dict[str, object]:
    """Parse errors.yaml directly (the codegen package isn't a backend dep).

    The full validator path (description-safety, 5xx PII guard,
    duplicate-code detection) runs in ``packages/error-contracts/tests/``.
    This test focuses on the structural floor that protects the
    backend's view of the wire contract.
    """
    # PyYAML is a direct dev dep declared at ``[dependency-groups.dev]``
    # in ``apps/backend/pyproject.toml``: the codegen package isn't a
    # backend dep, so the YAML reader is re-declared directly here. The
    # ``ImportError`` block below is a diagnostic safety net for the case
    # where a future dev-deps refactor drops pyyaml from the backend
    # group; ``pragma: no cover`` excludes it from the coverage gate.
    import json

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover — diagnostic-only
        msg = (
            "PyYAML is required to run errors.yaml invariant tests. "
            "Install it as a backend test dep if the transitive chain drops it."
        )
        raise ImportError(msg) from exc

    raw = _ERRORS_YAML_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    # Round-trip through json so the test handles only json-compatible
    # types (PyYAML returns plain dicts/lists/strings for safe_load).
    return json.loads(json.dumps(parsed))


def test_errors_yaml_declares_supported_version(errors_data: dict[str, object]) -> None:
    """``version`` must be 1 — the generator only knows how to emit v1 shapes."""
    assert errors_data["version"] == 1


def test_errors_yaml_declares_at_least_baseline_codes(
    errors_data: dict[str, object],
) -> None:
    """The YAML must declare at least ``_MIN_CODE_COUNT`` codes.

    Catches a regression where a YAML refactor strips all codes (the
    generator emits zero files, ``task check:errors`` passes the
    git-diff gate against the empty tree, and every consumer breaks).
    """
    errors = errors_data["errors"]
    assert isinstance(errors, dict)
    assert len(errors) >= _MIN_CODE_COUNT


def test_errors_yaml_every_code_has_non_empty_description(
    errors_data: dict[str, object],
) -> None:
    """Every error must declare a non-empty ``description`` field —
    descriptions ship as the generated docstring and are the only
    human-readable summary outside the YAML itself."""
    errors = errors_data["errors"]
    assert isinstance(errors, dict)
    for code, spec in errors.items():
        assert isinstance(spec, dict), f"{code} must be a mapping"
        description = spec.get("description")
        assert isinstance(description, str), f"{code} description must be a str"
        assert description.strip(), f"{code} description must be non-empty"


_HTTP_STATUS_FLOOR = 400
_HTTP_STATUS_CEILING = 599


def test_errors_yaml_every_http_status_is_in_error_range(
    errors_data: dict[str, object],
) -> None:
    """Every error's ``http_status`` must be in the 400-599 range —
    problem+json is for error responses; non-error statuses would
    fail the ProblemDetails ``ge=400`` schema constraint at runtime."""
    errors = errors_data["errors"]
    assert isinstance(errors, dict)
    for code, spec in errors.items():
        assert isinstance(spec, dict)
        status = spec.get("http_status")
        assert isinstance(status, int), f"{code} http_status must be an int"
        assert _HTTP_STATUS_FLOOR <= status <= _HTTP_STATUS_CEILING, (
            f"{code} http_status {status} out of error range"
        )
