"""InferenceRequest wire schema — public POST body for the inference endpoint."""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams

# Per-key cap for metadata values: bounds payload size symmetrically with
# Message string-content limits and prevents `{"x": "<10MiB string>"}`-style
# memory amplification on the LAN-trusted-but-not-infallible consumer path.
_METADATA_VALUE_MAX_LENGTH = 4096


class InferenceRequest(BaseModel):
    """Request envelope accepted by the inference endpoint.

    `model` is a logical name the registry resolves to a concrete
    backend tag — never a backend-specific tag itself. `metadata` is a
    pass-through for future per-project attribution; structural bounds
    (key count + per-value length) are enforced, content semantics are
    opaque.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    messages: list[Message] = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    params: ModelParams = Field(default_factory=ModelParams)
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def _bound_metadata_values(self) -> Self:
        for key, value in self.metadata.items():
            if isinstance(value, str) and len(value) > _METADATA_VALUE_MAX_LENGTH:
                msg = (
                    f"metadata[{key!r}] string value exceeds the "
                    f"{_METADATA_VALUE_MAX_LENGTH}-character cap."
                )
                raise ValueError(msg)
        return self
