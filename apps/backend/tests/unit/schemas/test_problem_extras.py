"""Unit tests for the ProblemExtras typed-extension declaration.

ProblemExtras is the BaseModel that lists the typed extension keys the
exception handler is allowed to spread on top of a ProblemDetails body.
The set of keys must be in lockstep with the codegen's RESERVED_PARAM_NAMES
(see ``test_problem_extras_drift_guard.py``).
"""

from types import NoneType, UnionType
from typing import get_args, get_origin

from app.schemas import ProblemExtras, ValidationErrorDetail


def test_problem_extras_validation_errors_key_is_typed_as_list_of_validation_error_detail() -> None:
    """ProblemExtras.validation_errors is typed as ``list[ValidationErrorDetail] | None``.

    The field is Optional (``= None`` default) so the runtime annotation
    is ``list[X] | None``. We unwrap the union arm, then assert the list
    element type points at ``ValidationErrorDetail``. Inspects the
    annotation directly rather than asserting on the literal we just
    constructed (which would have been tautological).
    """
    annotations = ProblemExtras.__annotations__
    assert "validation_errors" in annotations
    annotation = annotations["validation_errors"]
    # The field is ``list[ValidationErrorDetail] | None``; the union
    # origin is ``types.UnionType`` (PEP 604 syntax). Find the list arm.
    assert get_origin(annotation) is UnionType
    union_args = get_args(annotation)
    list_arms = [a for a in union_args if get_origin(a) is list]
    assert NoneType in union_args
    assert len(list_arms) == 1
    list_args = get_args(list_arms[0])
    assert len(list_args) == 1
    elem = list_args[0]
    if isinstance(elem, type):
        assert elem is ValidationErrorDetail
    else:
        # ForwardRef path (TYPE_CHECKING-imported symbol): repr carries the name.
        assert "ValidationErrorDetail" in repr(elem)
