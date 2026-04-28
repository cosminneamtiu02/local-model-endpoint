"""Unit tests on the JSON Schema produced by the F001 envelopes (LIP-E001-F001).

These exercise the Pydantic schema-emission path that FastAPI inlines into
`components.schemas` once the inference route lands in F002. The full
`/openapi.json` contract checks live in F002's contract suite; here we
verify the per-model schema shape directly so the contract is locked
ahead of router wiring.
"""

from typing import Any, cast

from pydantic import TypeAdapter

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


def test_message_schema_declares_additional_properties_false() -> None:
    schema = Message.model_json_schema()
    assert schema.get("additionalProperties") is False


def test_model_params_schema_declares_additional_properties_false() -> None:
    schema = ModelParams.model_json_schema()
    assert schema.get("additionalProperties") is False


def test_inference_request_schema_declares_additional_properties_false() -> None:
    schema = InferenceRequest.model_json_schema()
    assert schema.get("additionalProperties") is False


def test_inference_response_schema_declares_additional_properties_false() -> None:
    schema = InferenceResponse.model_json_schema()
    assert schema.get("additionalProperties") is False


def test_response_metadata_schema_declares_additional_properties_false() -> None:
    schema = ResponseMetadata.model_json_schema()
    assert schema.get("additionalProperties") is False


def test_response_metadata_schema_marks_finish_reason_as_enum() -> None:
    schema = ResponseMetadata.model_json_schema()
    finish_reason_schema = schema["properties"]["finish_reason"]
    assert finish_reason_schema.get("enum") == ["stop", "length", "timeout"]


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
