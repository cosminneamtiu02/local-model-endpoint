"""Unit tests for AudioContent (LIP-E001-F001).

Mirrors ImageContent's url/base64 internal-union semantics; the choice
was made jointly to keep multimodal parts symmetric until the adapter
layer translates to Ollama's wire format.
"""

import pytest
from pydantic import ValidationError

from app.features.inference.model.audio_content import AudioContent


def test_audio_content_accepts_url_only() -> None:
    part = AudioContent(url="https://example.com/clip.wav")
    assert part.type == "audio"
    assert part.url == "https://example.com/clip.wav"
    assert part.base64 is None


def test_audio_content_accepts_base64_only() -> None:
    part = AudioContent(base64="UklGRiQAAABXQVZF")
    assert part.type == "audio"
    assert part.url is None
    assert part.base64 == "UklGRiQAAABXQVZF"


def test_audio_content_rejects_both_url_and_base64() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        AudioContent(url="https://example.com/clip.wav", base64="UklGRiQAAABXQVZF")


def test_audio_content_rejects_neither_url_nor_base64() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        AudioContent()


def test_audio_content_rejects_empty_url() -> None:
    with pytest.raises(ValidationError):
        AudioContent(url="")


def test_audio_content_rejects_empty_base64() -> None:
    with pytest.raises(ValidationError):
        AudioContent(base64="")


def test_audio_content_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        AudioContent.model_validate(
            {"type": "audio", "url": "https://x", "bogus": 1},
        )
