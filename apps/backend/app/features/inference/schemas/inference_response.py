"""InferenceResponse wire schema — buffered JSON returned by the endpoint."""

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.caps import CONTENT_MAX_LENGTH
from app.features.inference.schemas.response_metadata import ResponseMetadata


class InferenceResponse(BaseModel):
    """Response envelope returned by the inference endpoint.

    `content` is the assistant-generated text. Streaming is out of v1
    scope — every response is buffered in full before return.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    # ``CONTENT_MAX_LENGTH`` (1 MiB) mirrors ``OllamaChatResult.content``'s
    # cap — the orchestrator copies content from there into this envelope
    # without re-validation, so the wire schema needs the same bound to
    # keep response amplification visible at every layer.
    content: str = Field(max_length=CONTENT_MAX_LENGTH)
    metadata: ResponseMetadata
