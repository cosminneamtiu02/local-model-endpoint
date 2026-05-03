"""Frozen-params invariant guard.

The exception handler dumps ``exc.params.model_dump(mode="json")`` and treats
the result as immutable when spreading at root level. A non-frozen subclass
that mutates params after construction (in a thread, in a future async path)
would corrupt the wire body. Every params class shipped via codegen MUST
declare ``model_config = ConfigDict(extra="forbid", frozen=True)``; this test
pins the invariant across the registry so a regression in the codegen
template fails CI rather than ship.
"""

import inspect
from typing import cast

import pytest
from pydantic import BaseModel

from app.exceptions import _generated  # pyright: ignore[reportPrivateImportUsage]


def _params_classes() -> list[type[BaseModel]]:
    """Return every ``*Params`` class re-exported from ``app.exceptions._generated``.

    The codegen emits one ``<Code>Params`` class per parameterized error code.
    Iterating the public surface of the generated package decouples the test
    from any specific error roster — adding a new parameterized error in
    errors.yaml automatically extends the test's coverage.
    """
    members = inspect.getmembers(_generated, inspect.isclass)
    return sorted(
        (cast("type[BaseModel]", cls) for name, cls in members if name.endswith("Params")),
        key=lambda c: c.__name__,
    )


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
