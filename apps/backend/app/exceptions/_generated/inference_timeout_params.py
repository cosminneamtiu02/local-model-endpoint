"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class InferenceTimeoutParams(BaseModel):
    """Parameters for INFERENCE_TIMEOUT error."""

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int
