"""Unit tests for TextContent (LIP-E001-F001)."""

import pytest
from pydantic import ValidationError

from app.features.inference.model.dos_caps import TEXT_PART_MAX_CHARS
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


def test_text_content_rejects_whitespace_only_text() -> None:
    # str_strip_whitespace + min_length=1 rejects whitespace-only inputs that
    # would otherwise bypass min_length=1 by being literally non-empty strings.
    with pytest.raises(ValidationError):
        TextContent(text="   ")


def test_text_content_rejects_oversize_text() -> None:
    # max_length caps the per-part DoS surface; one char over is rejected.
    oversize = TEXT_PART_MAX_CHARS + 1
    with pytest.raises(ValidationError):
        TextContent(text="x" * oversize)


def test_text_content_accepts_text_at_max_length() -> None:
    part = TextContent(text="x" * TEXT_PART_MAX_CHARS)
    assert len(part.text) == TEXT_PART_MAX_CHARS
