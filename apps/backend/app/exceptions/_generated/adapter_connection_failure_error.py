"""Generated from errors.yaml. Do not edit."""

from typing import TYPE_CHECKING, ClassVar, cast, override

from app.exceptions._generated.adapter_connection_failure_params import (
    AdapterConnectionFailureParams,
)
from app.exceptions.base import DomainError

if TYPE_CHECKING:
    from pydantic import BaseModel


class AdapterConnectionFailureError(DomainError):
    """Adapter (e.g. Ollama) connection or response failure (LIP-E003-F003)"""

    code: ClassVar[str] = "ADAPTER_CONNECTION_FAILURE"
    http_status: ClassVar[int] = 502
    type_uri: ClassVar[str] = "urn:lip:error:adapter-connection-failure"
    title: ClassVar[str] = "Adapter Connection Failure"
    detail_template: ClassVar[str] = "Inference backend '{backend}' failed: {reason}"

    @override
    def __init__(self, *, backend: str, reason: str) -> None:
        super().__init__(params=AdapterConnectionFailureParams(backend=backend, reason=reason))

    @override
    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        params = cast("BaseModel", self.params)
        return self.detail_template.format(**params.model_dump())
