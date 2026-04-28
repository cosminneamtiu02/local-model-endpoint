"""Image variant of a multimodal Message content part."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImageContent(BaseModel):
    """Image content part of a Message.

    Carries either a public `url` reference or a base64-encoded `base64`
    blob. Exactly one must be set; the adapter layer translates whichever
    form is present into Ollama's wire format.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    type: Literal["image"] = "image"
    # max_length on url bounds long-link DoS; max_length on base64 bounds the
    # per-part inline-blob DoS at ~15 MB binary (20 MiB of base64 ≈ 15 MB raw).
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    base64: str | None = Field(default=None, min_length=1, max_length=20_971_520)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        if (self.url is None) == (self.base64 is None):
            msg = "ImageContent requires exactly one of `url` or `base64`"
            raise ValueError(msg)
        return self
