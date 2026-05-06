"""InferenceResponse wire schema — buffered JSON returned by the endpoint."""

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.dos_caps import CONTENT_MAX_LENGTH
from app.features.inference.schemas.response_metadata import ResponseMetadata


class InferenceResponse(BaseModel):
    """Response envelope returned by the inference endpoint.

    `content` is the assistant-generated text. Streaming is out of v1
    scope — every response is buffered in full before return.
    """

    # ``str_strip_whitespace`` is intentionally NOT set: this envelope ships
    # the assistant-generated text verbatim from ``OllamaChatResult.content``.
    # Trimming would silently drop trailing newlines on fenced code blocks
    # and other deliberate whitespace from the model. ``content`` has no
    # ``min_length`` so there is nothing for the strip to defend against
    # — the cap below is the only invariant.
    model_config = ConfigDict(extra="forbid", frozen=True)

    # ``CONTENT_MAX_LENGTH`` (1 MiB) mirrors ``OllamaChatResult.content``'s
    # cap — the orchestrator copies content from there into this envelope
    # without re-validation, so the wire schema needs the same bound to
    # keep response amplification visible at every layer. ``min_length=0``
    # is the deliberate "empty content is OK" stance (mirrors the
    # ``OllamaChatResult.content`` declaration); the explicit ``0``
    # documents the intent on the OpenAPI wire schema for SDK consumers.
    content: str = Field(
        min_length=0,
        max_length=CONTENT_MAX_LENGTH,
        description="Assistant-generated text returned verbatim from the backend.",
    )
    metadata: ResponseMetadata = Field(
        description="Per-response routing/timing/token metadata.",
    )
