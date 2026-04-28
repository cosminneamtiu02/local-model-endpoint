"""Unit tests for ImageContent (LIP-E001-F001).

Per the F001 open question on multimodal serialization, ImageContent
carries an internal union over `url` (public reference) and `base64`
(base64-encoded bytes). Exactly one must be set; the validator enforces
that invariant at the schema boundary. The field name `base64` matches
the wire vocabulary the adapter feature consumes.
"""

import pytest
from pydantic import ValidationError

from app.features.inference.model.image_content import ImageContent


def test_image_content_accepts_url_only() -> None:
    part = ImageContent(url="https://example.com/cat.png")
    assert part.type == "image"
    assert part.url == "https://example.com/cat.png"
    assert part.base64 is None


def test_image_content_accepts_base64_only() -> None:
    part = ImageContent(base64="iVBORw0KGgo=")
    assert part.type == "image"
    assert part.url is None
    assert part.base64 == "iVBORw0KGgo="


def test_image_content_rejects_both_url_and_base64() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        ImageContent(url="https://example.com/x.png", base64="iVBORw0KGgo=")


def test_image_content_rejects_neither_url_nor_base64() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        ImageContent()


def test_image_content_rejects_empty_url() -> None:
    with pytest.raises(ValidationError):
        ImageContent(url="")


def test_image_content_rejects_empty_base64() -> None:
    with pytest.raises(ValidationError):
        ImageContent(base64="")


def test_image_content_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        ImageContent.model_validate(
            {"type": "image", "url": "https://x", "bogus": 1},
        )


def test_image_content_dump_excludes_unset_base64_when_url_supplied() -> None:
    part = ImageContent(url="https://example.com/cat.png")
    dumped = part.model_dump()
    assert dumped["type"] == "image"
    assert dumped["url"] == "https://example.com/cat.png"
    assert dumped["base64"] is None
