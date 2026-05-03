"""Image variant of a multimodal Message content part."""

from typing import Annotated, Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from app.features.inference.model._caps import BASE64_MEDIA_MAX_CHARS, URL_MAX_CHARS


class ImageContent(BaseModel):
    """Image content part of a Message.

    Carries either a public `url` reference or a base64-encoded `base64`
    blob. Exactly one must be set; the adapter layer translates whichever
    form is present into Ollama's wire format.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    type: Literal["image"] = "image"
    # ``AnyHttpUrl`` clamps the scheme to http/https and rejects ``file://``,
    # ``javascript:``, etc. — defense-in-depth vs SSRF / scheme-confusion when
    # the URL-fetching adapter path lands. The max_length still applies (as a
    # belt-and-suspenders bound on the string form). ``base64`` cap bounds the
    # per-part inline-blob DoS at ~15 MB binary (20 MiB of base64 ≈ 15 MB raw).
    url: Annotated[AnyHttpUrl, Field(max_length=URL_MAX_CHARS)] | None = None
    base64: str | None = Field(default=None, min_length=1, max_length=BASE64_MEDIA_MAX_CHARS)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        if (self.url is None) == (self.base64 is None):
            msg = "ImageContent requires exactly one of `url` or `base64`"
            raise ValueError(msg)
        return self
