"""Unit tests for Message (LIP-E001-F001)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.features.inference.model.dos_caps import TEXT_PART_MAX_CHARS
from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.message import Message
from app.features.inference.model.text_content import TextContent

# max_length=32 caps content-part cardinality (DoS axis); kept symmetric
# with the schema constant. Imported here because the cap lives on the
# Pydantic Field, not in the shared caps module.
_MESSAGE_CONTENT_LIST_MAX_PARTS = 32


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
        content=[TextContent(text="A"), ImageContent(base64="iV..")],
    )
    assert isinstance(msg.content, list)
    assert len(msg.content) == 2
    assert isinstance(msg.content[0], TextContent)
    assert isinstance(msg.content[1], ImageContent)


def test_message_dump_with_multipart_content_includes_type_discriminator() -> None:
    msg = Message(
        role="user",
        content=[TextContent(text="A"), ImageContent(base64="iV..")],
    )
    dumped = msg.model_dump()
    assert dumped["role"] == "user"
    assert isinstance(dumped["content"], list)
    assert dumped["content"][0]["type"] == "text"
    assert dumped["content"][1]["type"] == "image"


def test_message_rejects_invalid_role() -> None:
    with pytest.raises(ValidationError, match="role"):
        Message.model_validate({"role": "invalid", "content": "x"})


@pytest.mark.parametrize("role", ["user", "assistant", "system"])
def test_message_accepts_each_allowed_role_with_string_content(role: str) -> None:
    """Parametrized over allowed roles to avoid three near-duplicate per-role tests."""
    # ``role: str`` is wider than the ``Literal`` union the schema requires;
    # pyright catches the runtime-narrow case without seeing that the
    # parametrize values are exactly the three Literal members.
    msg = Message(role=role, content="hi")  # pyright: ignore[reportArgumentType]
    assert msg.role == role


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


def test_message_rejects_empty_string_content() -> None:
    # min_length=1 on the str arm rejects "" — caught at the union arm, not
    # at the model_validator layer. Anchor on Pydantic v2's
    # ``string_too_short`` message so the test fails IF the regression
    # is a different category (e.g. discriminator routing) that happens
    # to mention ``content``.
    with pytest.raises(ValidationError, match="at least 1 character"):
        Message(role="user", content="")


def test_message_rejects_whitespace_only_string_content() -> None:
    # str_strip_whitespace strips before length check.
    with pytest.raises(ValidationError, match="at least 1 character"):
        Message(role="user", content="   ")


def test_message_rejects_empty_content_list() -> None:
    # min_length=1 on the list arm rejects []. Pydantic v2 emits
    # ``too_short`` with "at least 1 item" for lists.
    with pytest.raises(ValidationError, match="at least 1 item"):
        Message(role="user", content=[])


def test_message_rejects_oversize_content_list() -> None:
    # max_length=32 caps content-part cardinality (DoS axis). Pydantic v2
    # emits ``too_long`` with "at most N items" for lists.
    with pytest.raises(ValidationError, match=r"at most \d+ item"):
        Message(
            role="user",
            content=[TextContent(text="x") for _ in range(_MESSAGE_CONTENT_LIST_MAX_PARTS + 1)],
        )


def test_message_rejects_oversize_string_content() -> None:
    """Boundary computed from the shared cap (oversize = max + 1) so a future cap bump auto-tracks."""
    oversize = TEXT_PART_MAX_CHARS + 1
    # ``at most N characters`` is Pydantic v2's ``string_too_long`` message.
    with pytest.raises(ValidationError, match=r"at most \d+ character"):
        Message(role="user", content="x" * oversize)


# ── Boundary-inclusive accept tests ──────────────────────────────────


def test_message_accepts_string_content_at_max_length() -> None:
    """Boundary-inclusive: TEXT_PART_MAX_CHARS chars is the largest legal content."""
    msg = Message(role="user", content="x" * TEXT_PART_MAX_CHARS)
    assert isinstance(msg.content, str)
    assert len(msg.content) == TEXT_PART_MAX_CHARS


def test_message_accepts_content_list_at_max_size() -> None:
    """Boundary-inclusive: 32 parts is the largest legal multimodal content list."""
    parts: list[TextContent | ImageContent] = [
        TextContent(text="x") for _ in range(_MESSAGE_CONTENT_LIST_MAX_PARTS)
    ]
    # ``list[TextContent | ImageContent]`` widens beyond the schema's
    # ``list[ContentPart]`` Annotated alias; the union is structurally
    # identical at runtime but pyright cannot see through the schema
    # alias without an explicit cast.
    msg = Message(role="user", content=parts)  # pyright: ignore[reportArgumentType]
    assert isinstance(msg.content, list)
    assert len(msg.content) == _MESSAGE_CONTENT_LIST_MAX_PARTS
