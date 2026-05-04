"""Unit tests for ImageContent (LIP-E001-F001).

Per the LIP-E001-F001 open question on multimodal serialization,
ImageContent carries an internal union over `url` (public reference)
and `base64` (base64-encoded bytes). Exactly one must be set; the
validator enforces that invariant at the schema boundary. The field
name `base64` matches the wire vocabulary the adapter feature consumes.
"""

import pytest
from pydantic import ValidationError

from app.features.inference.model.caps import BASE64_MEDIA_MAX_CHARS, URL_MAX_CHARS
from app.features.inference.model.image_content import ImageContent


def test_image_content_accepts_url_only() -> None:
    part = ImageContent.model_validate({"url": "https://example.com/cat.png"})
    assert part.type == "image"
    # ``part.url`` is a Pydantic AnyHttpUrl (SSRF defense), so compare
    # via ``str()`` to match the wire form.
    assert str(part.url) == "https://example.com/cat.png"
    assert part.base64 is None


def test_image_content_accepts_base64_only() -> None:
    part = ImageContent(base64="iVBORw0KGgo=")
    assert part.type == "image"
    assert part.url is None
    assert part.base64 == "iVBORw0KGgo="


def test_image_content_rejects_both_url_and_base64() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        # ``model_validate`` (not direct kwargs) keeps the AnyHttpUrl tightening
        # happy under pyright strict — kwargs would force ``str`` literals
        # through an ``AnyHttpUrl`` parameter that is no longer ``str``.
        ImageContent.model_validate(
            {"url": "https://example.com/x.png", "base64": "iVBORw0KGgo="},
        )


def test_image_content_rejects_neither_url_nor_base64() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        ImageContent()


def test_image_content_rejects_empty_url() -> None:
    with pytest.raises(ValidationError):
        ImageContent.model_validate({"url": ""})


def test_image_content_rejects_empty_base64() -> None:
    with pytest.raises(ValidationError):
        ImageContent(base64="")


def test_image_content_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        ImageContent.model_validate(
            {"type": "image", "url": "https://example.com/x", "bogus": 1},
        )


def test_image_content_dump_excludes_unset_base64_when_url_supplied() -> None:
    part = ImageContent.model_validate({"url": "https://example.com/cat.png"})
    dumped = part.model_dump(mode="json")
    assert dumped["type"] == "image"
    assert dumped["url"] == "https://example.com/cat.png"
    assert dumped["base64"] is None


def test_image_content_rejects_non_http_scheme_url() -> None:
    """SSRF defense: the URL field is now AnyHttpUrl which accepts only
    http/https. ``file://`` / ``javascript:`` are rejected at the schema
    boundary so the URL-fetching adapter (when it lands) cannot reach
    arbitrary schemes."""
    with pytest.raises(ValidationError):
        ImageContent.model_validate({"url": "file:///etc/passwd"})


def test_image_content_rejects_oversize_base64() -> None:
    # caps the inline-blob DoS surface; one char over the cap is rejected.
    oversize = BASE64_MEDIA_MAX_CHARS + 1
    with pytest.raises(ValidationError):
        ImageContent(base64="A" * oversize)


def test_image_content_rejects_oversize_url() -> None:
    """URL-length cap rejects a URL longer than ``URL_MAX_CHARS``."""
    # ``http://x/`` is 9 chars; pad to one beyond the cap.
    pad_len = (URL_MAX_CHARS + 1) - len("http://x/")
    with pytest.raises(ValidationError):
        ImageContent.model_validate({"url": "http://x/" + ("a" * pad_len)})
