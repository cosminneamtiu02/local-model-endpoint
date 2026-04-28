"""Audio variant of a multimodal Message content part."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AudioContent(BaseModel):
    """Audio content part of a Message.

    Symmetric with ImageContent: carries either a public `url` reference
    or a base64-encoded `base64` blob. Exactly one must be set.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["audio"] = "audio"
    url: str | None = Field(default=None, min_length=1)
    base64: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        if (self.url is None) == (self.base64 is None):
            msg = "AudioContent requires exactly one of `url` or `base64`"
            raise ValueError(msg)
        return self
