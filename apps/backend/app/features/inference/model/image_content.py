"""Image variant of a multimodal Message content part."""

from typing import Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

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
    # the URL-fetching adapter path lands. The string-form length cap is
    # enforced by ``_bound_url_length`` below — Pydantic's ``Field(max_length=)``
    # on a ``Url`` typed field is silently a no-op (the constraint targets
    # ``str``-typed fields, not ``Url`` instances). ``base64`` cap bounds the
    # per-part inline-blob DoS at ~15 MB binary (20 MiB of base64 ≈ 15 MB raw).
    url: AnyHttpUrl | None = None
    base64: str | None = Field(default=None, min_length=1, max_length=BASE64_MEDIA_MAX_CHARS)

    @field_validator("url", mode="after")
    @classmethod
    def _bound_url_length(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        """Cap the string form of the URL at ``URL_MAX_CHARS``.

        Pydantic ``Field(max_length=...)`` does NOT apply to ``Url``-typed
        fields (the constraint targets ``str`` core schemas), so the bound
        is enforced here against ``len(str(value))``.
        """
        if value is not None and len(str(value)) > URL_MAX_CHARS:
            msg = f"url exceeds {URL_MAX_CHARS}-char cap"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        ensure_exactly_one_url_or_base64(self, "ImageContent")
        return self
