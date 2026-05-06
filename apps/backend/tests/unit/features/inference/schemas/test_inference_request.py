"""Unit tests for InferenceRequest (LIP-E001-F001)."""

import pytest
from pydantic import ValidationError

from app.features.inference.model.dos_caps import (
    METADATA_KEY_MAX_LENGTH,
    METADATA_NESTED_CARDINALITY_MAX,
    METADATA_VALUE_MAX_LENGTH,
)
from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams
from app.features.inference.schemas.inference_request import InferenceRequest


def test_inference_request_constructs_with_required_fields() -> None:
    req = InferenceRequest(
        messages=[Message(role="user", content="hi")],
        model="gemma-4-e2b",
    )
    assert req.model == "gemma-4-e2b"
    assert len(req.messages) == 1
    assert isinstance(req.params, ModelParams)
    assert req.metadata == {}


def test_inference_request_rejects_empty_messages_list() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        InferenceRequest(messages=[], model="x")


def test_inference_request_accepts_arbitrary_metadata_dict() -> None:
    req = InferenceRequest(
        messages=[Message(role="user", content="hi")],
        model="x",
        metadata={"project_id": "abc", "trace_id": 42, "nested": {"k": 1}},
    )
    assert req.metadata == {"project_id": "abc", "trace_id": 42, "nested": {"k": 1}}


def test_inference_request_rejects_unknown_top_level_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        InferenceRequest.model_validate(
            {
                "messages": [{"role": "user", "content": "hi"}],
                "model": "x",
                "stream": True,
            },
        )


def test_inference_request_default_params_dump_excludes_unset() -> None:
    req = InferenceRequest(
        messages=[Message(role="user", content="hi")],
        model="x",
    )
    dumped = req.model_dump(exclude_unset=True)
    assert "params" not in dumped


def test_inference_request_rejects_empty_model_name() -> None:
    with pytest.raises(ValidationError, match="model"):
        InferenceRequest(messages=[Message(role="user", content="hi")], model="")


def test_inference_request_params_passes_through() -> None:
    req = InferenceRequest(
        messages=[Message(role="user", content="hi")],
        model="x",
        params=ModelParams(temperature=0.7),
    )
    assert req.params.temperature == 0.7


def test_inference_request_routes_message_dicts_through_message_validator() -> None:
    req = InferenceRequest.model_validate(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "model": "x",
        },
    )
    assert isinstance(req.messages[0], Message)
    assert req.messages[0].role == "user"


def test_inference_request_rejects_metadata_with_oversized_nested_dict_key() -> None:
    """A long key one level deep must trip the nested-key cap.

    Defense against the documented bypass surface: ``metadata={"safe":
    {"<long-key>": "v"}}`` would otherwise sneak past the top-level
    ``METADATA_KEY_MAX_LENGTH`` Annotated cap (which only binds top-level
    keys).
    """
    overlong_key = "x" * (METADATA_KEY_MAX_LENGTH + 1)
    with pytest.raises(ValidationError, match="nested key"):
        InferenceRequest(
            messages=[Message(role="user", content="hi")],
            model="x",
            metadata={"safe": {overlong_key: "v"}},
        )


def test_inference_request_rejects_metadata_with_oversized_nested_list() -> None:
    """A list with > METADATA_NESTED_CARDINALITY_MAX elements must be rejected.

    Defense against the documented bypass surface: ``metadata={"safe":
    [None] * 1_000_000}`` would otherwise inflate request memory under
    the documented invariant that the metadata path is bounded on all
    DoS axes.
    """
    too_many = [None] * (METADATA_NESTED_CARDINALITY_MAX + 1)
    # ``list[None]`` is structurally a JsonValue but pyright's invariant
    # ``list[T]`` typing rejects it against ``list[JsonValue]``. Pydantic
    # accepts the value at runtime (None is part of the JsonValue union);
    # the schema rejects it on the cardinality cap, not the type.
    with pytest.raises(ValidationError, match="nested list"):
        InferenceRequest(
            messages=[Message(role="user", content="hi")],
            model="x",
            metadata={"safe": too_many},  # pyright: ignore[reportArgumentType]
        )


def test_inference_request_rejects_metadata_with_oversized_nested_dict() -> None:
    """A dict with > METADATA_NESTED_CARDINALITY_MAX entries must be rejected."""
    too_many = {f"k{i}": "v" for i in range(METADATA_NESTED_CARDINALITY_MAX + 1)}
    # See sibling-test rationale above: ``dict[str, str]`` is structurally
    # a JsonValue but pyright invariance rejects it against ``dict[str,
    # JsonValue]``. Runtime accepts; the schema rejects on cardinality.
    with pytest.raises(ValidationError, match="nested dict"):
        InferenceRequest(
            messages=[Message(role="user", content="hi")],
            model="x",
            metadata={"safe": too_many},  # pyright: ignore[reportArgumentType]
        )


def test_inference_request_rejects_metadata_with_oversized_string_value() -> None:
    """A nested string value over METADATA_VALUE_MAX_LENGTH must be rejected."""
    overlong = "x" * (METADATA_VALUE_MAX_LENGTH + 1)
    with pytest.raises(ValidationError, match="string value exceeds"):
        InferenceRequest(
            messages=[Message(role="user", content="hi")],
            model="x",
            metadata={"safe": overlong},
        )


def test_inference_request_recurses_into_nested_list_strings() -> None:
    """The recursive walk must check string elements inside nested lists."""
    overlong = "x" * (METADATA_VALUE_MAX_LENGTH + 1)
    with pytest.raises(ValidationError, match="string value exceeds"):
        InferenceRequest(
            messages=[Message(role="user", content="hi")],
            model="x",
            metadata={"safe": ["short", overlong]},
        )
