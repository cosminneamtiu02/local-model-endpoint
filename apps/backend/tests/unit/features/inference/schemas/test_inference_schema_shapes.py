"""Unit tests on the JSON Schema produced by the F001 envelopes (LIP-E001-F001).

These exercise the Pydantic schema-emission path that FastAPI inlines into
`components.schemas` once the inference route lands in a follow-up
feature. The full `/openapi.json` contract checks live in that feature's
contract suite; here we verify the per-model schema shape directly so
the contract is locked ahead of router wiring.

Note: bare `model_json_schema()` produces refs into `#/$defs/...`, while
FastAPI rewrites them to `#/components/schemas/...` via its
`ref_template`. This test file checks the schema *shape* (keys, types,
constraints), not the ref-path strings — so the unit-level proxy is
ref-template-agnostic and remains valid once FastAPI mounts the schemas.
"""

from typing import Any, cast

import pytest
from pydantic import BaseModel, TypeAdapter

from app.features.inference.model.content_part import ContentPart
from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams
from app.features.inference.schemas.inference_request import InferenceRequest
from app.features.inference.schemas.inference_response import InferenceResponse
from app.features.inference.schemas.response_metadata import ResponseMetadata


def test_message_schema_marks_role_as_enum() -> None:
    schema = Message.model_json_schema()
    role_schema = schema["properties"]["role"]
    assert role_schema.get("enum") == ["user", "assistant", "system"]


def test_message_schema_renders_content_as_oneof() -> None:
    schema = Message.model_json_schema()
    content_schema = schema["properties"]["content"]
    variants = content_schema.get("anyOf") or content_schema.get("oneOf") or []
    assert variants, "Message.content should be a union"


@pytest.mark.parametrize(
    "model_cls",
    [Message, ModelParams, InferenceRequest, InferenceResponse, ResponseMetadata],
    ids=lambda c: c.__name__,
)
def test_schema_declares_additional_properties_false(model_cls: type[BaseModel]) -> None:
    """Every wire/value-object schema must close ``additionalProperties``.

    Parametrized over the five F001 models so a future schema added to the
    inference feature only needs a row in the ``model_cls`` list to inherit
    coverage — no new test function to write. The PEP 695 ID renderer keeps
    the per-class failure name human-readable in ``-v`` output.
    """
    schema = model_cls.model_json_schema()
    assert schema.get("additionalProperties") is False


def test_response_metadata_schema_marks_finish_reason_as_enum() -> None:
    """`finish_reason` is a `FinishReason` PEP 695 alias shared with the
    adapter; Pydantic emits a `$ref` into `$defs/FinishReason` (or, under
    FastAPI's mount, `components/schemas/FinishReason`) which holds the
    enum body. Resolve the ref before asserting the enum."""
    schema = ResponseMetadata.model_json_schema()
    finish_reason_schema = schema["properties"]["finish_reason"]
    ref = finish_reason_schema.get("$ref", "")
    finish_reason_name = ref.rsplit("/", 1)[-1]
    finish_reason_def = schema["$defs"][finish_reason_name]
    assert finish_reason_def.get("enum") == ["stop", "length", "timeout"]
    assert finish_reason_def.get("type") == "string"


def test_inference_request_schema_marks_messages_min_items() -> None:
    schema = InferenceRequest.model_json_schema()
    messages_schema = schema["properties"]["messages"]
    assert messages_schema.get("minItems") == 1


def test_content_part_json_schema_lists_three_variants() -> None:
    adapter: TypeAdapter[ContentPart] = TypeAdapter(ContentPart)
    schema = adapter.json_schema()
    variants = cast("list[dict[str, Any]]", schema.get("oneOf", []))
    titles = {v["$ref"].split("/")[-1] for v in variants}
    assert {"TextContent", "ImageContent", "AudioContent"}.issubset(titles)
