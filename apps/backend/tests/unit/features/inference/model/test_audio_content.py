"""Unit tests for AudioContent (LIP-E001-F001).

Mirrors ImageContent's url/base64 internal-union semantics; the choice
was made jointly to keep multimodal parts symmetric until the adapter
layer translates to Ollama's wire format.
"""

import pytest
from pydantic import ValidationError

from app.features.inference.model.audio_content import AudioContent
from app.features.inference.model.caps import BASE64_MEDIA_MAX_CHARS, URL_MAX_CHARS


def test_audio_content_accepts_url_only() -> None:
    part = AudioContent.model_validate({"url": "https://example.com/clip.wav"})
    assert part.type == "audio"
    # ``part.url`` is AnyHttpUrl (SSRF defense).
    assert str(part.url) == "https://example.com/clip.wav"
    assert part.base64 is None


def test_audio_content_rejects_non_http_scheme_url() -> None:
    """Symmetric with ImageContent — non-http(s) schemes are rejected."""
    with pytest.raises(ValidationError):
        AudioContent.model_validate({"url": "file:///etc/passwd"})


def test_audio_content_accepts_base64_only() -> None:
    part = AudioContent(base64="UklGRiQAAABXQVZF")
    assert part.type == "audio"
    assert part.url is None
    assert part.base64 == "UklGRiQAAABXQVZF"


def test_audio_content_rejects_both_url_and_base64() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        # ``model_validate`` (not direct kwargs) keeps pyright strict happy
        # under the AnyHttpUrl typing — direct kwargs would force a ``str``
        # literal through an ``AnyHttpUrl`` parameter.
        AudioContent.model_validate(
            {"url": "https://example.com/clip.wav", "base64": "UklGRiQAAABXQVZF"},
        )


def test_audio_content_rejects_neither_url_nor_base64() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        AudioContent()


def test_audio_content_rejects_empty_url() -> None:
    with pytest.raises(ValidationError):
        AudioContent.model_validate({"url": ""})


def test_audio_content_rejects_empty_base64() -> None:
    with pytest.raises(ValidationError):
        AudioContent(base64="")


def test_audio_content_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        AudioContent.model_validate(
            {"type": "audio", "url": "https://example.com/x", "bogus": 1},
        )


def test_audio_content_rejects_oversize_base64() -> None:
    """Caps the inline-blob DoS surface; one char over the cap is rejected."""
    oversize = BASE64_MEDIA_MAX_CHARS + 1
    with pytest.raises(ValidationError):
        AudioContent(base64="A" * oversize)


def test_audio_content_rejects_oversize_url() -> None:
    """URL-length cap rejects a URL longer than ``URL_MAX_CHARS``."""
    pad_len = (URL_MAX_CHARS + 1) - len("http://x/")
    with pytest.raises(ValidationError):
        AudioContent.model_validate({"url": "http://x/" + ("a" * pad_len)})
