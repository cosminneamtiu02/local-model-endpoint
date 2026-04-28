"""Unit tests for InferenceRequest (LIP-E001-F001)."""

import pytest
from pydantic import ValidationError

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
    with pytest.raises(ValidationError):
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
