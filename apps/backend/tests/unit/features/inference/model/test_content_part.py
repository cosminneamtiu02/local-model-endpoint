"""Unit tests for the ContentPart discriminated-union type alias (LIP-E001-F001)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from app.features.inference.model.audio_content import AudioContent
from app.features.inference.model.content_part import ContentPart
from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.text_content import TextContent

_ADAPTER: TypeAdapter[ContentPart] = TypeAdapter(ContentPart)


def test_content_part_routes_text_dict_to_text_content() -> None:
    part = _ADAPTER.validate_python({"type": "text", "text": "hello"})
    assert isinstance(part, TextContent)
    assert part.text == "hello"


def test_content_part_routes_image_dict_to_image_content() -> None:
    part = _ADAPTER.validate_python({"type": "image", "url": "https://example.com/x"})
    assert isinstance(part, ImageContent)
    # ``part.url`` is AnyHttpUrl (SSRF defense).
    assert str(part.url) == "https://example.com/x"


def test_content_part_routes_audio_dict_to_audio_content() -> None:
    part = _ADAPTER.validate_python({"type": "audio", "url": "https://example.com/x"})
    assert isinstance(part, AudioContent)
    assert str(part.url) == "https://example.com/x"


def test_content_part_rejects_unknown_discriminator_value() -> None:
    with pytest.raises(ValidationError, match=r"(does not match|expected tag|discriminator)"):
        _ADAPTER.validate_python({"type": "video", "url": "https://example.com/x"})


def test_content_part_rejects_missing_discriminator() -> None:
    with pytest.raises(ValidationError, match=r"(discriminator|tag)"):
        _ADAPTER.validate_python({"text": "hello"})


def test_content_part_rejects_audio_discriminator_with_text_arm_payload() -> None:
    """Cross-arm-payload negative: ``type="audio"`` with ``text`` field MUST fail.

    The discriminator-routing tests above cover the unknown-tag and the
    missing-tag cases. The cross-arm case (an ``audio``-tagged payload
    that carries ``text`` content but no ``url``/``base64``) exercises a
    different surface: the discriminator routes correctly to
    ``AudioContent``, but ``AudioContent``'s own ``model_validator``
    rejects "exactly one of url or base64". Without this test, a future
    routing change that silently bypassed the per-arm validator (e.g.
    switching to ``discriminator="kind"`` while still accepting ``type``
    keys) would only fail the per-arm tests in ``test_audio_content.py``,
    not the routing test surface here. Pinning the cross-arm rejection
    at the routing layer keeps the two contracts in lockstep.
    """
    with pytest.raises(ValidationError, match=r"(audio|url|base64)"):
        _ADAPTER.validate_python({"type": "audio", "text": "hello"})


def test_content_part_json_schema_renders_as_oneof() -> None:
    schema = _ADAPTER.json_schema()
    assert "oneOf" in schema
    discriminator_values = {ref["$ref"].split("/")[-1] for ref in schema["oneOf"]}
    assert {"TextContent", "ImageContent", "AudioContent"}.issubset(discriminator_values)
