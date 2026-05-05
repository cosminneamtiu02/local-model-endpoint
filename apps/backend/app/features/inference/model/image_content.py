"""Image variant of a multimodal Message content part."""

from typing import Annotated, Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, UrlConstraints, model_validator

from app.features.inference.model._validators import ensure_exactly_one_url_or_base64
from app.features.inference.model.caps import BASE64_MEDIA_MAX_CHARS, URL_MAX_CHARS


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
    # the URL-fetching adapter path lands. ``UrlConstraints(max_length=...)``
    # enforces the string-form length cap at the core-schema layer (``Field
    # (max_length=)`` is silently a no-op on Url-typed fields because the
    # constraint targets the ``str`` core schema, not ``Url`` instances).
    # ``base64`` cap bounds the per-part inline-blob DoS at ~15 MB binary
    # (20 MiB of base64 ≈ 15 MB raw).
    url: Annotated[AnyHttpUrl, UrlConstraints(max_length=URL_MAX_CHARS)] | None = None
    base64: str | None = Field(default=None, min_length=1, max_length=BASE64_MEDIA_MAX_CHARS)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        ensure_exactly_one_url_or_base64(self, "ImageContent")
        return self
