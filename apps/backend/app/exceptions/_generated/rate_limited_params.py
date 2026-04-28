"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class RateLimitedParams(BaseModel):
    """Parameters for RATE_LIMITED error: Client exceeded rate limit"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    retry_after_seconds: int
