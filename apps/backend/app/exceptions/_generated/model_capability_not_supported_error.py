"""Generated from errors.yaml. Do not edit."""

from typing import TYPE_CHECKING, ClassVar, cast

from app.exceptions._generated.model_capability_not_supported_params import (
    ModelCapabilityNotSupportedParams,
)
from app.exceptions.base import DomainError

if TYPE_CHECKING:
    from pydantic import BaseModel


class ModelCapabilityNotSupportedError(DomainError):
    """Error: MODEL_CAPABILITY_NOT_SUPPORTED."""

    code: ClassVar[str] = "MODEL_CAPABILITY_NOT_SUPPORTED"
    http_status: ClassVar[int] = 422
    type_uri: ClassVar[str] = "urn:lip:error:model-capability-not-supported"
    title: ClassVar[str] = "Model Capability Not Supported"
    detail_template: ClassVar[str] = (
        "Model '{model}' does not support requested capability '{requested_capability}'."
    )

    def __init__(self, *, model: str, requested_capability: str) -> None:
        super().__init__(
            params=ModelCapabilityNotSupportedParams(
                model=model,
                requested_capability=requested_capability,
            ),
        )

    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        params = cast("BaseModel", self.params)
        return self.detail_template.format(**params.model_dump())
