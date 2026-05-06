"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class AdapterConnectionFailureParams(BaseModel):
    """Parameters for ADAPTER_CONNECTION_FAILURE error.

    Adapter (e.g. Ollama) connection or response failure (LIP-E003-F003).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: str
    reason: str
