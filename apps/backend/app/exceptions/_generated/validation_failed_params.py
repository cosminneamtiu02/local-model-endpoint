"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class ValidationFailedParams(BaseModel):
    """Parameters for VALIDATION_FAILED error."""

    model_config = ConfigDict(extra="forbid")

    field: str
    reason: str
