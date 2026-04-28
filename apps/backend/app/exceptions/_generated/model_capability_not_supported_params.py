"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel


class ModelCapabilityNotSupportedParams(BaseModel):
    """Parameters for MODEL_CAPABILITY_NOT_SUPPORTED error."""

    model: str
    requested_capability: str
