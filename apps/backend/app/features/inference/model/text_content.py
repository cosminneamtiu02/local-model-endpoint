"""Text variant of a multimodal Message content part."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TextContent(BaseModel):
    """Text content part of a Message.

    Discriminator value `"text"` routes the parent Message's
    `content: list[ContentPart]` field to this variant.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    type: Literal["text"] = "text"
    # max_length=131072 (128 KiB) bounds the per-part DoS surface; comfortably
    # above any realistic single-turn prompt within Gemma's 128K-token context
    # at ~4 chars/token. str_strip_whitespace prevents min_length=1 from being
    # bypassed with whitespace-only input.
    text: str = Field(min_length=1, max_length=131072)
