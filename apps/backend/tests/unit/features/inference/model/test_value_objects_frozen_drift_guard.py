"""Drift-guard: every inference value-object class is frozen at runtime.

Mirror of ``tests/unit/exceptions/test_params_frozen_invariant.py`` for
the inference value-object family. The Params drift-guard auto-extends
to any new generated class; this test does the same for the hand-written
inference value-objects published via ``app.features.inference.model``'s
``__all__``.

The ``frozen=True`` flag on each model_config is load-bearing for the
downstream invariants: ``ContentPart`` discriminator routing, the
``OllamaChatResult.finish_reason`` Literal, and ``ModelParams``'s
``temperature``/``top_p`` SSRF-irrelevant-but-mutation-leak-prone
defaults all assume each instance is immutable post-construction. A flag
flip to ``False`` would silently let mutation bypass these contracts;
asserting the BEHAVIOR (assignment raises) instead of the FLAG
(``model_config["frozen"] is True``) catches both flag drift AND a
future Pydantic v3 change to what ``frozen`` means.

Discovered classes are read off ``app.features.inference.model.__all__``
so a new value-object addition is auto-covered without per-class test
maintenance.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from app.features.inference import model as model_pkg

_VALID_KWARGS: dict[str, dict[str, object]] = {
    "AudioContent": {"type": "audio", "url": "https://example.com/a.wav"},
    "ImageContent": {"type": "image", "url": "https://example.com/i.png"},
    "Message": {"role": "user", "content": "hello"},
    "ModelParams": {},
    "OllamaChatResult": {
        "content": "x",
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "finish_reason": "stop",
    },
    "TextContent": {"type": "text", "text": "hi"},
}


def _value_object_classes() -> list[tuple[str, type[BaseModel]]]:
    """Resolve the value-object classes from the public __all__ surface.

    Reading off ``__all__`` (rather than a hand-coded list) is the
    "drift-guard auto-extends" property: a future addition (e.g.
    VideoContent for LIP-E002-F001) lands the test automatically the
    moment it is exported.
    """
    classes: list[tuple[str, type[BaseModel]]] = []
    for name in model_pkg.__all__:
        cls = getattr(model_pkg, name)
        # Only iterate Pydantic models — a future re-export of a
        # non-Pydantic helper (e.g. a frozen dataclass) would otherwise
        # crash this test. The frozen-invariant for non-Pydantic types
        # is owned by their own test surface, not this drift-guard.
        if isinstance(cls, type) and issubclass(cls, BaseModel):
            classes.append((name, cls))
    return classes


@pytest.mark.parametrize(
    ("name", "model_cls"),
    _value_object_classes(),
    ids=[name for name, _ in _value_object_classes()],
)
def test_inference_value_object_is_frozen_at_runtime(name: str, model_cls: type[BaseModel]) -> None:
    """Each value-object instance rejects post-construction field assignment."""
    kwargs = _VALID_KWARGS.get(name)
    if kwargs is None:
        msg = (
            f"Add a valid kwargs dict to ``_VALID_KWARGS`` for {name!r} so the "
            "frozen-invariant test can construct an instance to mutate."
        )
        raise AssertionError(msg)
    instance = model_cls.model_validate(kwargs)
    # Pick the first field on the class as the mutation target; for
    # ``ModelParams`` (zero required fields), pick the first declared
    # optional field. Either way, ``setattr`` to a sentinel string MUST
    # raise ValidationError under ``frozen=True``.
    field_name = next(iter(model_cls.model_fields))
    with pytest.raises(ValidationError, match="frozen"):
        # ``setattr`` (not ``instance.field = ...``) so pyright doesn't
        # statically reject the assignment under ``frozen=True``; the
        # runtime ValidationError is what we want to assert.
        setattr(instance, field_name, "frozen-violation-sentinel")
