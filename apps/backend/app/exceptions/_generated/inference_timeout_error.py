"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar

from app.exceptions._generated.inference_timeout_params import InferenceTimeoutParams
from app.exceptions.base import DomainError


class InferenceTimeoutError(DomainError):
    """Error: INFERENCE_TIMEOUT."""

    code: ClassVar[str] = "INFERENCE_TIMEOUT"
    http_status: ClassVar[int] = 504
    type_uri: ClassVar[str] = "urn:lip:error:inference-timeout"
    title: ClassVar[str] = "Inference Timeout"
    detail_template: ClassVar[str] = "Inference exceeded the {timeout_seconds}-second timeout."

    def __init__(self, *, timeout_seconds: int) -> None:
        super().__init__(params=InferenceTimeoutParams(timeout_seconds=timeout_seconds))

    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        assert self.params is not None  # parameterized error
        return self.detail_template.format(**self.params.model_dump())
