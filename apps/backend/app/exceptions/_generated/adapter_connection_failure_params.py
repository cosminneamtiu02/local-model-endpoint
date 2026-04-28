"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class AdapterConnectionFailureParams(BaseModel):
    """Parameters for ADAPTER_CONNECTION_FAILURE error."""

    model_config = ConfigDict(extra="forbid")

    backend: str
    reason: str
