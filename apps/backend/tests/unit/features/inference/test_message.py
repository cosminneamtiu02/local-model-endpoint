"""Unit tests for Message (LIP-E001-F001)."""

import pytest
from pydantic import ValidationError

from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.message import Message
from app.features.inference.model.text_content import TextContent


def test_message_constructs_with_simple_string_content() -> None:
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"


def test_message_dump_with_string_content_returns_minimal_shape() -> None:
    msg = Message(role="user", content="hello")
    assert msg.model_dump() == {"role": "user", "content": "hello"}


def test_message_constructs_with_multipart_list_content() -> None:
    msg = Message(
        role="user",
        content=[TextContent(text="A"), ImageContent(url="https://x")],
    )
    assert isinstance(msg.content, list)
    assert len(msg.content) == 2
    assert isinstance(msg.content[0], TextContent)
    assert isinstance(msg.content[1], ImageContent)


def test_message_dump_with_multipart_content_includes_type_discriminator() -> None:
    msg = Message(
        role="user",
        content=[TextContent(text="A"), ImageContent(url="https://x")],
    )
    dumped = msg.model_dump()
    assert dumped["role"] == "user"
    assert isinstance(dumped["content"], list)
    assert dumped["content"][0]["type"] == "text"
    assert dumped["content"][1]["type"] == "image"


def test_message_rejects_invalid_role() -> None:
    with pytest.raises(ValidationError, match="role"):
        Message.model_validate({"role": "invalid", "content": "x"})


def test_message_accepts_assistant_role_with_string_content() -> None:
    msg = Message(role="assistant", content="reply")
    assert msg.role == "assistant"


def test_message_accepts_system_role_with_string_content() -> None:
    msg = Message(role="system", content="prompt")
    assert msg.role == "system"


def test_message_accepts_assistant_role_with_multipart_content() -> None:
    msg = Message(role="assistant", content=[TextContent(text="A")])
    assert msg.role == "assistant"
    assert isinstance(msg.content, list)


def test_message_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        Message.model_validate({"role": "user", "content": "x", "stream": True})


def test_message_routes_dict_content_through_content_part_discriminator() -> None:
    msg = Message.model_validate(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "A"},
                {"type": "image", "url": "https://x"},
            ],
        },
    )
    assert isinstance(msg.content, list)
    assert isinstance(msg.content[0], TextContent)
    assert isinstance(msg.content[1], ImageContent)
