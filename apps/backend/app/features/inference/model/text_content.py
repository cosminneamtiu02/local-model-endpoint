"""Text variant of a multimodal Message content part."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TextContent(BaseModel):
    """Text content part of a Message.

    Discriminator value `"text"` routes the parent Message's
    `content: list[ContentPart]` field to this variant.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["text"] = "text"
    text: str = Field(min_length=1)
