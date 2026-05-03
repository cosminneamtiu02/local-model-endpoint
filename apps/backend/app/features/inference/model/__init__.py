"""Inference value-objects — Pydantic models that survive backend swaps."""

from app.features.inference.model.audio_content import AudioContent

# ContentPart and FinishReason are PEP 695 type aliases, not runtime
# classes — kept out of __all__. Type annotations elsewhere can still
# `from app.features.inference.model import ContentPart` (or
# `FinishReason`) because the import lines below bind the names;
# __all__ only governs `from ... import *` behavior.
from app.features.inference.model.content_part import ContentPart as ContentPart
from app.features.inference.model.finish_reason import FinishReason as FinishReason
from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams
from app.features.inference.model.ollama_chat_result import OllamaChatResult
from app.features.inference.model.text_content import TextContent

__all__ = [
    "AudioContent",
    "ImageContent",
    "Message",
    "ModelParams",
    "OllamaChatResult",
    "TextContent",
]
