"""Audio variant of a multimodal Message content part."""

from typing import Annotated, Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, UrlConstraints, model_validator

from app.features.inference.model._validators import ensure_exactly_one_url_or_base64
from app.features.inference.model.dos_caps import BASE64_MEDIA_MAX_CHARS, URL_MAX_CHARS


class AudioContent(BaseModel):
    """Audio content part of a Message.

    Carries either a public ``url`` reference or a base64-encoded ``base64``
    blob. Exactly one must be set; the adapter layer translates whichever
    form is present into Ollama's wire format. Field-level shape and caps
    are symmetric with :class:`ImageContent` so a parametrized contract
    test can exercise both via one fixture.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    type: Literal["audio"] = "audio"
    # ``AnyHttpUrl`` clamps URL schemes to http/https (defense-in-depth vs
    # SSRF / scheme-confusion when the URL-fetching adapter path lands).
    # ``UrlConstraints(max_length=...)`` enforces the string-form length
    # cap at the core-schema layer (``Field(max_length=)`` is silently a
    # no-op on Url-typed fields because the constraint targets the ``str``
    # core schema, not ``Url`` instances). 20 MiB base64 ≈ 15 MB binary
    # covers practical voice clips; longer audio belongs in a streaming-
    # upload path, not this body.
    #
    # FORWARD (URL-fetching adapter — LIP-E001-F002 multimodal extension
    # OR a future translation-layer change): ``AnyHttpUrl`` accepts any
    # http/https host with no private/loopback exclusion. Today nothing
    # fetches these URLs (the translation layer raises
    # ``NotImplementedError`` for URL-only multimodal at
    # ``ollama_translation.py``), so the SSRF surface is dormant. When a
    # consumer-supplied URL becomes a thing LIP fetches on the
    # consumer's behalf, add an SSRF clamp REJECTING private/loopback
    # hosts here — INVERTED relative to ``Settings.ollama_host``'s
    # ``is_private_host`` clamp (Settings allows private; URL-fetched
    # content must FORBID private to avoid metadata-service / loopback-
    # bounce attacks). Land the clamp in the same PR that wires the
    # URL-fetch adapter so it cannot ship ahead of the protection.
    url: Annotated[AnyHttpUrl, UrlConstraints(max_length=URL_MAX_CHARS)] | None = None
    base64: str | None = Field(default=None, min_length=1, max_length=BASE64_MEDIA_MAX_CHARS)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        ensure_exactly_one_url_or_base64(self, "AudioContent")
        return self
