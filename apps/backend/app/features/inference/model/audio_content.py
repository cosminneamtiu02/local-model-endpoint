"""Audio variant of a multimodal Message content part."""

from typing import Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.features.inference.model._validators import ensure_exactly_one_url_or_base64
from app.features.inference.model.caps import BASE64_MEDIA_MAX_CHARS, URL_MAX_CHARS


class AudioContent(BaseModel):
    """Audio content part of a Message.

    Symmetric with ImageContent: carries either a public `url` reference
    or a base64-encoded `base64` blob. Exactly one must be set.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    type: Literal["audio"] = "audio"
    # Mirrors ImageContent caps. ``AnyHttpUrl`` clamps URL schemes to http/https
    # (defense-in-depth vs SSRF). The string-form length cap is enforced by
    # ``_bound_url_length`` below — Pydantic's ``Field(max_length=)`` on a
    # ``Url`` typed field is silently a no-op. 20 MiB base64 ≈ 15 MB binary
    # covers practical voice clips; longer audio belongs in a streaming-upload
    # path, not this body.
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
        ensure_exactly_one_url_or_base64(self, "AudioContent")
        return self
