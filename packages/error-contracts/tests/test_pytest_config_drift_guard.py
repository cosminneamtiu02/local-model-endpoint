"""Drift-guard for the error-contracts pytest config invariants.

Mirror of ``apps/backend/tests/unit/test_pytest_asyncio_config.py`` for
the error-contracts workspace. The backend pins ``asyncio_mode = "auto"``
because every async test in the suite relies on auto-decoration; this
workspace deliberately OMITS ``asyncio_mode`` because all codegen tests
are sync (per the comment block at ``packages/error-contracts/pyproject.toml:22``).

Without this guard, a future contributor adding the FIRST async test to
the codegen tree would land it un-collected (pytest-asyncio's default of
``strict`` skips assertions on un-decorated async tests), and CI would
stay green. The drift-guard pins both the deliberate omission AND the
reasoning so the next contributor adding an async test knows to extend
the workspace's pyproject in lockstep.

Also pins ``xfail_strict = True`` (symmetric with the backend) so a
flip back to the pytest default of ``False`` would silently allow
stale xfails to ship.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_asyncio_mode_omitted_until_first_async_test_lands() -> None:
    """``asyncio_mode`` is intentionally absent from this workspace's
    pyproject because every codegen test is sync today.

    This test is the canary for the deliberate omission. The first async
    test added to ``packages/error-contracts/tests/`` will silently
    no-op (pytest-asyncio default mode is ``strict``, which skips
    un-decorated async tests). Adding the async test must be paired
    with adding ``asyncio_mode = "auto"`` (and ``pytest-asyncio`` as a
    dev-dep) in lockstep — when that lands, this test should flip its
    assertion to mirror the backend's
    ``test_asyncio_mode_is_auto`` instead.
    """
    workspace_root = Path(__file__).resolve().parents[1]
    pyproject = workspace_root / "pyproject.toml"
    with pyproject.open("rb") as f:
        config = tomllib.load(f)
    pytest_options = config["tool"]["pytest"]["ini_options"]
    asyncio_mode = pytest_options.get("asyncio_mode")
    assert asyncio_mode is None, (
        f"``asyncio_mode`` was unexpectedly set to {asyncio_mode!r} in "
        "packages/error-contracts/pyproject.toml. Codegen tests are sync "
        "today (per the in-source comment); if a contributor is adding "
        "the first async test, also add ``pytest-asyncio`` to "
        "[dependency-groups].dev and update this drift-guard to assert "
        "``asyncio_mode == 'auto'`` (mirror of "
        "``apps/backend/tests/unit/test_pytest_asyncio_config.py``)."
    )


def test_xfail_strict_is_true() -> None:
    """``xfail_strict = true`` MUST be set so unexpectedly-passing xfails
    fail the run (forces the author to remove the marker rather than
    leaving stale xfails in the suite).

    Symmetric pin with ``apps/backend/tests/unit/test_pytest_asyncio_config.py``.
    Without this, a flip back to the pytest default of ``False`` would
    silently re-enable the stale-xfail antipattern across this workspace.
    """
    workspace_root = Path(__file__).resolve().parents[1]
    pyproject = workspace_root / "pyproject.toml"
    with pyproject.open("rb") as f:
        config = tomllib.load(f)
    pytest_options = config["tool"]["pytest"]["ini_options"]
    xfail_strict = pytest_options.get("xfail_strict")
    assert xfail_strict is True, (
        f"``xfail_strict`` must be ``True`` so unexpectedly-passing xfails "
        f"fail the run; got {xfail_strict!r}. See "
        "``packages/error-contracts/pyproject.toml:xfail_strict`` and the "
        "matching backend pin in "
        "``apps/backend/tests/unit/test_pytest_asyncio_config.py``."
    )


def test_python_classes_sentinel_matches_backend() -> None:
    """``python_classes = ["NoTestClassesAllowed"]`` mirrors backend.

    The Taskfile target ``check:test-class-regex-sync`` enforces the
    cross-workspace text equality of this pin too, but a workspace-local
    drift-guard reads as the canonical source of truth at the test layer
    rather than as a shell exit code in CI logs.
    """
    workspace_root = Path(__file__).resolve().parents[1]
    pyproject = workspace_root / "pyproject.toml"
    with pyproject.open("rb") as f:
        config = tomllib.load(f)
    pytest_options = config["tool"]["pytest"]["ini_options"]
    python_classes = pytest_options.get("python_classes")
    assert python_classes == ["NoTestClassesAllowed"], (
        f"``python_classes`` must be ``['NoTestClassesAllowed']`` per the "
        f"no-test-class CLAUDE.md sacred rule (collector-layer enforcement); "
        f"got {python_classes!r}."
    )
