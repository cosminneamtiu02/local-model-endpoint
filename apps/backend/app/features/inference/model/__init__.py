"""Inference value-objects — Pydantic models that survive backend swaps."""

from app.features.inference.model.audio_content import AudioContent
from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams
from app.features.inference.model.ollama_chat_result import OllamaChatResult
from app.features.inference.model.text_content import TextContent

# ContentPart and FinishReason are PEP 695 type aliases. Consumers needing them
# import from the leaf module directly (`from app.features.inference.model.
# content_part import ContentPart`); a package-level re-export would just be
# scaffolding for hypothetical-future-consumer use cases that haven't appeared.

__all__ = [
    "AudioContent",
    "ImageContent",
    "Message",
    "ModelParams",
    "OllamaChatResult",
    "TextContent",
]
