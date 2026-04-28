"""Message value-object — one turn of a conversation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.features.inference.model.content_part import ContentPart


class Message(BaseModel):
    """One conversation turn.

    `content` is either a plain string (the simple, single-turn
    happy-path) or a list of `ContentPart` variants for multimodal
    inputs. Role/multimodal compatibility (e.g., whether `assistant`
    messages may carry image parts) is enforced at the adapter layer
    (E003-F002), not here.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant", "system"]
    content: str | list[ContentPart]
