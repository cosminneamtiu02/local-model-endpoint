"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class ModelCapabilityNotSupportedParams(BaseModel):
    """Parameters for MODEL_CAPABILITY_NOT_SUPPORTED error: Request requires a capability the model does not advertise (LIP-E001-F002)"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    requested_capability: str
