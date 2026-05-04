"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class RegistryNotFoundParams(BaseModel):
    """Parameters for REGISTRY_NOT_FOUND error.

    Logical model name not present in the model registry (LIP-E002-F001)
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_name: str
