"""Image variant of a multimodal Message content part."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator


class ImageContent(BaseModel):
    """Image content part of a Message.

    The F001 open question on multimodal serialization is resolved here
    by carrying an internal union: either a public `url` reference or a
    base64-encoded `data` blob. Exactly one must be set; the adapter
    layer (E003-F002) translates whichever form is present into Ollama's
    wire format.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["image"] = "image"
    url: str | None = None
    data: str | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        if (self.url is None) == (self.data is None):
            msg = "ImageContent requires exactly one of `url` or `data`"
            raise ValueError(msg)
        return self
