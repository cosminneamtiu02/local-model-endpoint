"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class InferenceTimeoutParams(BaseModel):
    """Parameters for INFERENCE_TIMEOUT error.

    Inference exceeded the per-request timeout (LIP-E004-F003).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_seconds: int
