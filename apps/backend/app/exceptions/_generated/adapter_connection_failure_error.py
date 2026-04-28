"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar

from app.exceptions._generated.adapter_connection_failure_params import (
    AdapterConnectionFailureParams,
)
from app.exceptions.base import DomainError


class AdapterConnectionFailureError(DomainError):
    """Error: ADAPTER_CONNECTION_FAILURE."""

    code: ClassVar[str] = "ADAPTER_CONNECTION_FAILURE"
    http_status: ClassVar[int] = 502
    type_uri: ClassVar[str] = "urn:lip:error:adapter-connection-failure"
    title: ClassVar[str] = "Adapter Connection Failure"
    detail_template: ClassVar[str] = "Inference backend '{backend}' failed: {reason}"

    def __init__(self, *, backend: str, reason: str) -> None:
        super().__init__(params=AdapterConnectionFailureParams(backend=backend, reason=reason))

    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        assert self.params is not None  # parameterized error
        return self.detail_template.format(**self.params.model_dump())
