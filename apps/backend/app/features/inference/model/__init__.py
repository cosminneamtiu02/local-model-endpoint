"""Inference value-objects — Pydantic models that survive backend swaps."""

from app.features.inference.model.audio_content import AudioContent

# ContentPart is a type alias, not a runtime class — not in __all__.
# Type annotations elsewhere can still
# `from app.features.inference.model import ContentPart`
# because the import line below binds the name; __all__ only governs
# `from ... import *` behaviour.
from app.features.inference.model.content_part import ContentPart as ContentPart
from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams
from app.features.inference.model.text_content import TextContent

__all__ = [
    "AudioContent",
    "ImageContent",
    "Message",
    "ModelParams",
    "TextContent",
]
