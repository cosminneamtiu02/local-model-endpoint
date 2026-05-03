"""Text variant of a multimodal Message content part."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model._caps import TEXT_PART_MAX_CHARS


class TextContent(BaseModel):
    """Text content part of a Message.

    Discriminator value `"text"` routes the parent Message's
    `content: list[ContentPart]` field to this variant.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    type: Literal["text"] = "text"
    # ``TEXT_PART_MAX_CHARS`` (128 KiB) bounds the per-part DoS surface;
    # see app.features.inference.model._caps for the rationale.
    # str_strip_whitespace prevents min_length=1 from being bypassed with
    # whitespace-only input.
    text: str = Field(min_length=1, max_length=TEXT_PART_MAX_CHARS)
