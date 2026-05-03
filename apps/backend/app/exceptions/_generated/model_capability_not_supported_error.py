"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar, cast, override

from app.exceptions._generated.model_capability_not_supported_params import (
    ModelCapabilityNotSupportedParams,
)
from app.exceptions.base import DomainError


class ModelCapabilityNotSupportedError(DomainError):
    """Request requires a capability the model does not advertise (LIP-E001-F002)"""

    code: ClassVar[str] = "MODEL_CAPABILITY_NOT_SUPPORTED"
    http_status: ClassVar[int] = 422
    type_uri: ClassVar[str] = "urn:lip:error:model-capability-not-supported"
    title: ClassVar[str] = "Model Capability Not Supported"
    detail_template: ClassVar[str] = (
        "Model '{model_name}' does not support requested capability '{requested_capability}'."
    )

    @override
    def __init__(self, *, model_name: str, requested_capability: str) -> None:
        super().__init__(
            params=ModelCapabilityNotSupportedParams(
                model_name=model_name,
                requested_capability=requested_capability,
            ),
        )

    @override
    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        params = cast("ModelCapabilityNotSupportedParams", self.params)
        return self.detail_template.format(**params.model_dump())
