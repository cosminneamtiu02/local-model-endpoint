"""InferenceResponse wire schema — buffered JSON returned by the endpoint."""

from pydantic import BaseModel, ConfigDict

from app.features.inference.schemas.response_metadata import ResponseMetadata


class InferenceResponse(BaseModel):
    """Response envelope returned by the inference endpoint.

    `content` is the assistant-generated text. Streaming is out of v1
    scope — every response is buffered in full before return.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    metadata: ResponseMetadata
