"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class ValidationFailedParams(BaseModel):
    """Parameters for VALIDATION_FAILED error: Request payload failed validation"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    reason: str
