"""Unit tests for the ProblemExtras typed-extension declaration.

ProblemExtras is the TypedDict (or BaseModel post-migration) that lists
the typed extension keys the exception handler is allowed to spread on top
of a ProblemDetails body. The set of keys must be in lockstep with the
codegen's RESERVED_PARAM_NAMES (see ``test_problem_extras_drift_guard.py``).
"""

from typing import get_args, get_origin

from app.schemas import ProblemExtras, ValidationErrorDetail


def test_problem_extras_validation_errors_key_is_typed_as_list_of_validation_error_detail() -> None:
    """ProblemExtras carries ``validation_errors`` typed as ``list[ValidationErrorDetail]``.

    Inspects the annotation directly rather than asserting on the literal
    we just constructed (which would have been tautological). The runtime
    inspection covers both the TypedDict shape and (post AGENT-SCHEMAS
    migration) the BaseModel shape — both expose ``__annotations__`` with
    the same string-form annotation.

    ``get_type_hints`` handles forward references (``ValidationErrorDetail``
    is imported under TYPE_CHECKING in problem_extras.py); fall back to
    raw ``__annotations__`` repr for the TypedDict case where
    ``include_extras=True`` may still leave a ForwardRef.
    """
    annotations = ProblemExtras.__annotations__
    assert "validation_errors" in annotations
    annotation = annotations["validation_errors"]
    # If the annotation evaluated to a real type, get_origin returns ``list``;
    # otherwise (still a string from TYPE_CHECKING) the repr carries the names.
    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        assert len(args) == 1
        # The arg is either a class (post-migration) or a ForwardRef pointing
        # at ValidationErrorDetail.
        arg = args[0]
        if isinstance(arg, type):
            assert arg is ValidationErrorDetail
        else:
            assert "ValidationErrorDetail" in repr(arg)
    else:
        # TypedDict path: the annotation is still a string under
        # ``from __future__ import annotations`` semantics.
        annotation_repr = str(annotation)
        assert "list[" in annotation_repr
        assert "ValidationErrorDetail" in annotation_repr
