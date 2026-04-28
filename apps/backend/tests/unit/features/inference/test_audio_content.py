"""Unit tests for AudioContent (LIP-E001-F001).

Mirrors ImageContent's url/data internal-union semantics; the choice was
made jointly to keep multimodal parts symmetric until the adapter layer
(E003-F002) translates to Ollama's wire format.
"""

import pytest
from pydantic import ValidationError

from app.features.inference.model.audio_content import AudioContent


def test_audio_content_accepts_url_only() -> None:
    part = AudioContent(url="https://example.com/clip.wav")
    assert part.type == "audio"
    assert part.url == "https://example.com/clip.wav"
    assert part.data is None


def test_audio_content_accepts_base64_data_only() -> None:
    part = AudioContent(data="UklGRiQAAABXQVZF")
    assert part.type == "audio"
    assert part.url is None
    assert part.data == "UklGRiQAAABXQVZF"


def test_audio_content_rejects_both_url_and_data() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        AudioContent(url="https://example.com/clip.wav", data="UklGRiQAAABXQVZF")


def test_audio_content_rejects_neither_url_nor_data() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        AudioContent()


def test_audio_content_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        AudioContent.model_validate(
            {"type": "audio", "url": "https://x", "bogus": 1},
        )
