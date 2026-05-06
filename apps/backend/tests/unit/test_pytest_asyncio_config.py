"""Drift-guard for the pytest-asyncio loop-scope lockstep invariant.

``apps/backend/pyproject.toml``'s ``[tool.pytest.ini_options]`` block
pins both ``asyncio_default_fixture_loop_scope`` and
``asyncio_default_test_loop_scope`` to ``session`` in lockstep. The
12-line comment above those settings explains why: pytest-asyncio 1.3
treats the two as INDEPENDENT settings, so a mix (one ``session``,
the other unset → defaults to ``function``) triggers ``ScopeMismatch``
the first time a session-scoped async fixture is added.

Today no session-scoped async fixture exists, so the mismatch is
invisible at runtime. A future migration (pytest-asyncio 2.x where the
two keys may consolidate, or a contributor flipping one for "perf")
would silently drift one off ``session`` while the other stays — the
suite stays green until the first session-scoped async fixture lands,
which then surfaces as a confusing ScopeMismatch at unrelated PR time.

Pin the lockstep mechanically via ``tomllib`` so a drift fires loudly at
test time, attributing the regression to the pyproject change directly.
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
