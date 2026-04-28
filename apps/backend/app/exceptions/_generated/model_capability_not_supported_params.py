"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class ModelCapabilityNotSupportedParams(BaseModel):
    """Parameters for MODEL_CAPABILITY_NOT_SUPPORTED error."""

    model_config = ConfigDict(extra="forbid")

    model: str
    requested_capability: str
