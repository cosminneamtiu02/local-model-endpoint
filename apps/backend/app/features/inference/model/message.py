"""Message value-object — one turn of a conversation."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.content_part import ContentPart


class Message(BaseModel):
    """One conversation turn.

    `content` is either a plain string (the simple, single-turn happy
    path) or a list of ContentPart variants for multimodal inputs.
    Role/multimodal compatibility is enforced at the adapter layer,
    not here.

    `union_mode="left_to_right"` pins the resolution order so a plain
    string is matched as `str` first, never as an iterable; this defends
    against Pydantic's smart-union routing edge cases on `str | list`.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant", "system"]
    content: Annotated[str | list[ContentPart], Field(union_mode="left_to_right")]
