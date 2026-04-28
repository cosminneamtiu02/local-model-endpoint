"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel


class InferenceTimeoutParams(BaseModel):
    """Parameters for INFERENCE_TIMEOUT error."""

    timeout_seconds: int
