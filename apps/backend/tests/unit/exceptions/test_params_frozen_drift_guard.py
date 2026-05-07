"""Frozen-params invariant guard.

The exception handler dumps ``exc.params.model_dump(mode="json")`` and treats
the result as immutable when spreading at root level. A non-frozen subclass
that mutates params after construction (in a thread, in a future async path)
would corrupt the wire body. Every params class shipped via codegen MUST
declare ``model_config = ConfigDict(extra="forbid", frozen=True)``; this test
pins the invariant across the registry so a regression in the codegen
template fails CI rather than ship.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

import app.exceptions as exceptions_pkg


def _params_classes() -> list[type[BaseModel]]:
    """Return every ``*Params`` class re-exported from ``app.exceptions``.

    Reads the public re-export surface (``app.exceptions.__all__``) so the
    test depends on the same import path that production code uses — no
    private ``_generated`` poke. Adding a new parameterized error in
    errors.yaml lands a new ``*Params`` re-export and auto-extends the
    test's coverage.
    """
    classes: list[type[BaseModel]] = []
    for name in exceptions_pkg.__all__:
        if not name.endswith("Params"):
            continue
        cls = getattr(exceptions_pkg, name)
        if isinstance(cls, type) and issubclass(cls, BaseModel):
            classes.append(cls)
    return sorted(classes, key=lambda c: c.__name__)


@pytest.mark.parametrize("params_cls", _params_classes(), ids=lambda c: c.__name__)
def test_params_class_is_frozen_and_extra_forbid(params_cls: type[BaseModel]) -> None:
    """Every Params class config declares both ``frozen=True`` and ``extra='forbid'``."""
    config = params_cls.model_config
    assert config.get("frozen") is True, (
        f"{params_cls.__name__}: frozen must be True for the handler to safely "
        f"treat exc.params.model_dump() as immutable"
    )
    assert config.get("extra") == "forbid", (
        f"{params_cls.__name__}: extra must be 'forbid' so a YAML param drift "
        f"cannot inject extra wire keys"
    )


def test_at_least_one_params_class_exists_in_registry() -> None:
    """Sanity check that the parametrize fixture isn't silently empty."""
    assert _params_classes(), "Expected at least one *Params class in app.exceptions._generated"
