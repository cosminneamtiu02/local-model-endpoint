"""InferenceRequest wire schema — public POST body for the inference endpoint."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams


class InferenceRequest(BaseModel):
    """Request envelope accepted by the inference endpoint.

    `model` is a logical name the registry resolves to a concrete
    backend tag — never a backend-specific tag itself. `metadata` is a
    pass-through for future per-project attribution (project_id,
    request_id, trace_id) which v1 reserves space for without
    validating contents.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    # max_length on messages caps a single inference body; 64 is far
    # above any realistic conversation chain on Gemma's 128K context.
    messages: list[Message] = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    params: ModelParams = Field(default_factory=ModelParams)
    # metadata stays dict[str, Any] to honor the "v1 reserves space
    # without validating contents" contract, but max_length=16 caps the
    # number of keys so a malicious LAN consumer cannot blow up the
    # process with `{"x_<n>": <huge>}` style payloads.
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=16)
