"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar

from app.exceptions._generated.registry_not_found_params import RegistryNotFoundParams
from app.exceptions.base import DomainError


class RegistryNotFoundError(DomainError):
    """Error: REGISTRY_NOT_FOUND."""

    code: ClassVar[str] = "REGISTRY_NOT_FOUND"
    http_status: ClassVar[int] = 404
    type_uri: ClassVar[str] = "urn:lip:error:registry-not-found"
    title: ClassVar[str] = "Model Not Found in Registry"
    detail_template: ClassVar[str] = "Model '{model}' is not registered with this provider."

    def __init__(self, *, model: str) -> None:
        super().__init__(params=RegistryNotFoundParams(model=model))

    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        assert self.params is not None  # parameterized error
        return self.detail_template.format(**self.params.model_dump())
