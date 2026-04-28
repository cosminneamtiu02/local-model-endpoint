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

    model_config = ConfigDict(extra="forbid")

    messages: list[Message] = Field(min_length=1)
    model: str = Field(min_length=1)
    params: ModelParams = Field(default_factory=ModelParams)
    metadata: dict[str, Any] = Field(default_factory=dict)
