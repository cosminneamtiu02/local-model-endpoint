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
