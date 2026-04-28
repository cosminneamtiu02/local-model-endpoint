"""Unit tests for ImageContent (LIP-E001-F001).

Per the F001 open question on multimodal serialization, ImageContent
carries an internal union over `url` (public reference) and `data`
(base64-encoded bytes). Exactly one must be set; the validator enforces
that invariant at the schema boundary.
"""

import pytest
from pydantic import ValidationError

from app.features.inference.model.image_content import ImageContent


def test_image_content_accepts_url_only() -> None:
    part = ImageContent(url="https://example.com/cat.png")
    assert part.type == "image"
    assert part.url == "https://example.com/cat.png"
    assert part.data is None


def test_image_content_accepts_base64_data_only() -> None:
    part = ImageContent(data="iVBORw0KGgo=")
    assert part.type == "image"
    assert part.url is None
    assert part.data == "iVBORw0KGgo="


def test_image_content_rejects_both_url_and_data() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        ImageContent(url="https://example.com/x.png", data="iVBORw0KGgo=")


def test_image_content_rejects_neither_url_nor_data() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        ImageContent()


def test_image_content_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        ImageContent.model_validate(
            {"type": "image", "url": "https://x", "bogus": 1},
        )


def test_image_content_dump_excludes_unset_data_when_url_supplied() -> None:
    part = ImageContent(url="https://example.com/cat.png")
    dumped = part.model_dump()
    assert dumped["type"] == "image"
    assert dumped["url"] == "https://example.com/cat.png"
    assert dumped["data"] is None
