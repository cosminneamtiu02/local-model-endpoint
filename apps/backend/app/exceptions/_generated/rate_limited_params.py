"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class RateLimitedParams(BaseModel):
    """Parameters for RATE_LIMITED error."""

    model_config = ConfigDict(extra="forbid")

    retry_after_seconds: int
