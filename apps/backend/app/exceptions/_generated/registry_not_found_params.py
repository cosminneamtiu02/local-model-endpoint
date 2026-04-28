"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel


class RegistryNotFoundParams(BaseModel):
    """Parameters for REGISTRY_NOT_FOUND error."""

    model: str
