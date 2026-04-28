"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class RegistryNotFoundParams(BaseModel):
    """Parameters for REGISTRY_NOT_FOUND error."""

    model_config = ConfigDict(extra="forbid")

    model: str
