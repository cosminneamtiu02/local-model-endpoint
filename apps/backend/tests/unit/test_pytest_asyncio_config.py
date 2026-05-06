"""Drift-guard for the pytest-asyncio config invariants.

``apps/backend/pyproject.toml``'s ``[tool.pytest.ini_options]`` block
pins both ``asyncio_default_fixture_loop_scope`` and
``asyncio_default_test_loop_scope`` to ``session`` in lockstep, and
``asyncio_mode = "auto"`` so every async test is auto-decorated. The
comment block above those settings explains why: pytest-asyncio 1.3
treats the two scope settings as INDEPENDENT (a mix triggers
``ScopeMismatch`` the first time a session-scoped async fixture is
added), and ``asyncio_mode``'s default is ``"strict"`` (a flip would
silently no-op every async test that lacks an explicit
``@pytest.mark.asyncio`` decorator — and no test in the suite carries
one, since the project relies on auto-detection).

Today no session-scoped async fixture exists, so the mismatch is
invisible at runtime. A future migration (pytest-asyncio 2.x where the
two keys may consolidate, or a contributor flipping one for "perf")
would silently drift one off ``session`` while the other stays — the
suite stays green until the first session-scoped async fixture lands,
which then surfaces as a confusing ScopeMismatch at unrelated PR time.

Pin all three invariants mechanically via ``tomllib`` so a drift fires
loudly at test time, attributing the regression to the pyproject
change directly.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_asyncio_default_loop_scopes_in_lockstep() -> None:
    """``asyncio_default_fixture_loop_scope`` and
    ``asyncio_default_test_loop_scope`` MUST share the same value.

    See ``apps/backend/pyproject.toml`` lines around the
    ``asyncio_default_*`` settings for the upstream rationale.
    """
    # ``parents[2]`` from ``tests/unit/test_pytest_asyncio_config.py`` is
    # ``apps/backend/`` (the workspace root that owns the pyproject).
    workspace_root = Path(__file__).resolve().parents[2]
    pyproject = workspace_root / "pyproject.toml"
    with pyproject.open("rb") as f:
        config = tomllib.load(f)
    pytest_options = config["tool"]["pytest"]["ini_options"]
    fixture_scope = pytest_options.get("asyncio_default_fixture_loop_scope")
    test_scope = pytest_options.get("asyncio_default_test_loop_scope")
    assert fixture_scope == test_scope, (
        f"asyncio_default_fixture_loop_scope ({fixture_scope!r}) and "
        f"asyncio_default_test_loop_scope ({test_scope!r}) MUST stay in "
        f"lockstep; see pyproject.toml's ScopeMismatch rationale."
    )
    # Both also documented as ``"session"`` today — pin that explicitly so
    # a contributor flipping both to ``"function"`` for "perf" trips the
    # test and reads the rationale before merging.
    assert fixture_scope == "session", (
        f"both asyncio loop scopes must be 'session' per the apps/backend "
        f"pyproject rationale block (test perf trade-off accepted); got "
        f"{fixture_scope!r}"
    )


def test_asyncio_mode_is_auto() -> None:
    """``asyncio_mode = "auto"`` is what auto-decorates every async test.

    pytest-asyncio's default is ``"strict"`` — a flip would silently
    no-op every async test that lacks an explicit
    ``@pytest.mark.asyncio`` decorator. No test in the suite carries
    that decorator (the project relies on auto-detection), so a
    deletion or flip of this key in ``pyproject.toml`` would silently
    skip the entire async-test surface while the synchronous tests
    stay green. ``filterwarnings = ["error"]`` does NOT flag uncollected-
    async-as-sync tests, so this drift-guard is the canonical mechanical
    pin.
    """
    workspace_root = Path(__file__).resolve().parents[2]
    pyproject = workspace_root / "pyproject.toml"
    with pyproject.open("rb") as f:
        config = tomllib.load(f)
    pytest_options = config["tool"]["pytest"]["ini_options"]
    asyncio_mode = pytest_options.get("asyncio_mode")
    assert asyncio_mode == "auto", (
        f"``asyncio_mode`` must be ``'auto'`` so async tests auto-decorate; "
        f"got {asyncio_mode!r}. A flip to ``'strict'`` (or deletion → default "
        f"``'strict'``) would silently no-op every async test in the suite."
    )


def test_python_classes_sentinel_is_no_test_classes_allowed() -> None:
    """``python_classes = ["NoTestClassesAllowed"]`` is the silent-suppression
    backstop for CLAUDE.md sacred rule "no test classes".

    Pair with the loud ``pytest_sessionstart`` regex hook in
    ``tests/conftest.py``: the regex hook is the operator-facing fail; this
    sentinel makes pytest's collector silently skip class-based test methods
    so a contributor who somehow lands the class-based form past code review
    still gets zero coverage rather than green CI on uncollected methods.
    A flip back to the pytest default ``["Test*"]`` would silently re-enable
    class-based collection and defeat the no-test-class rule mechanically.
    """
    workspace_root = Path(__file__).resolve().parents[2]
    pyproject = workspace_root / "pyproject.toml"
    with pyproject.open("rb") as f:
        config = tomllib.load(f)
    pytest_options = config["tool"]["pytest"]["ini_options"]
    python_classes = pytest_options.get("python_classes")
    assert python_classes == ["NoTestClassesAllowed"], (
        f"``python_classes`` must be ``['NoTestClassesAllowed']`` so the "
        f"no-test-class CLAUDE.md sacred rule is mechanically enforced at "
        f"the collector layer; got {python_classes!r}. The Taskfile target "
        f"``check:test-class-regex-sync`` enforces lockstep with the "
        f"error-contracts workspace; this test pins the sentinel value."
    )


def test_python_files_pattern_locks_naming_convention() -> None:
    """``python_files = ["test_*.py"]`` locks CLAUDE.md's
    ``test_<unit>_<scenario>_<expected>`` naming convention at the
    collector layer.

    Default pytest also picks up ``*_test.py``, which would let a contributor
    land a misnamed file silently; pinning explicitly locks the convention
    mechanically so a flip would surface in CI.
    """
    workspace_root = Path(__file__).resolve().parents[2]
    pyproject = workspace_root / "pyproject.toml"
    with pyproject.open("rb") as f:
        config = tomllib.load(f)
    pytest_options = config["tool"]["pytest"]["ini_options"]
    python_files = pytest_options.get("python_files")
    python_functions = pytest_options.get("python_functions")
    assert python_files == ["test_*.py"], (
        f"``python_files`` must be ``['test_*.py']`` per CLAUDE.md naming "
        f"convention; got {python_files!r}."
    )
    assert python_functions == ["test_*"], (
        f"``python_functions`` must be ``['test_*']`` per CLAUDE.md naming "
        f"convention; got {python_functions!r}."
    )


def test_addopts_contains_strict_markers_and_strict_config() -> None:
    """``--strict-markers`` + ``--strict-config`` MUST be in ``addopts``.

    Without these flags, a typo in a pytest marker (``@pytest.mark.solw``
    instead of ``slow``) is a silent no-op rather than a hard failure;
    a typo in a ``[tool.pytest.ini_options]`` key (``asynxio_mode``
    instead of ``asyncio_mode``) is silently ignored. Both classes of
    typo are exactly the regressions ``--strict-*`` is designed to catch.
    """
    workspace_root = Path(__file__).resolve().parents[2]
    pyproject = workspace_root / "pyproject.toml"
    with pyproject.open("rb") as f:
        config = tomllib.load(f)
    pytest_options = config["tool"]["pytest"]["ini_options"]
    addopts = pytest_options.get("addopts", [])
    assert "--strict-markers" in addopts, (
        f"``--strict-markers`` must be in ``addopts`` so unknown markers "
        f"fail the run; got {addopts!r}."
    )
    assert "--strict-config" in addopts, (
        f"``--strict-config`` must be in ``addopts`` so unknown config "
        f"keys fail the run; got {addopts!r}."
    )
