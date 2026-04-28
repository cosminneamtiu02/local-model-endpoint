"""Unit tests for TextContent (LIP-E001-F001)."""

import pytest
from pydantic import ValidationError

from app.features.inference.model.text_content import TextContent


def test_text_content_constructs_with_text() -> None:
    part = TextContent(text="hello")
    assert part.type == "text"
    assert part.text == "hello"


def test_text_content_dump_includes_type_discriminator() -> None:
    part = TextContent(text="hello")
    assert part.model_dump() == {"type": "text", "text": "hello"}


def test_text_content_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        TextContent.model_validate({"type": "text", "text": "x", "bogus": 1})


def test_text_content_rejects_wrong_type_discriminator() -> None:
    with pytest.raises(ValidationError):
        TextContent.model_validate({"type": "image", "text": "x"})


def test_text_content_requires_text_field() -> None:
    with pytest.raises(ValidationError):
        TextContent.model_validate({"type": "text"})


def test_text_content_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        TextContent(text="")
