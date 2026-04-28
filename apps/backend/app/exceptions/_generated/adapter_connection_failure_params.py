"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel


class AdapterConnectionFailureParams(BaseModel):
    """Parameters for ADAPTER_CONNECTION_FAILURE error."""

    backend: str
    reason: str
