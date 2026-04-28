"""Generated from errors.yaml. Do not edit."""

from typing import TYPE_CHECKING, ClassVar, cast

from app.exceptions._generated.inference_timeout_params import InferenceTimeoutParams
from app.exceptions.base import DomainError

if TYPE_CHECKING:
    from pydantic import BaseModel


class InferenceTimeoutError(DomainError):
    """Inference exceeded the per-request timeout (LIP-E004-F003)"""

    code: ClassVar[str] = "INFERENCE_TIMEOUT"
    http_status: ClassVar[int] = 504
    type_uri: ClassVar[str] = "urn:lip:error:inference-timeout"
    title: ClassVar[str] = "Inference Timeout"
    detail_template: ClassVar[str] = "Inference exceeded the {timeout_seconds}-second timeout."

    def __init__(self, *, timeout_seconds: int) -> None:
        super().__init__(params=InferenceTimeoutParams(timeout_seconds=timeout_seconds))

    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        params = cast("BaseModel", self.params)
        return self.detail_template.format(**params.model_dump())
