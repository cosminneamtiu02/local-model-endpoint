"""Generated from errors.yaml. Do not edit."""

from typing import TYPE_CHECKING, ClassVar, cast, override

from app.exceptions._generated.registry_not_found_params import RegistryNotFoundParams
from app.exceptions.base import DomainError

if TYPE_CHECKING:
    from pydantic import BaseModel


class RegistryNotFoundError(DomainError):
    """Logical model name not present in the model registry (LIP-E002-F001)"""

    code: ClassVar[str] = "REGISTRY_NOT_FOUND"
    http_status: ClassVar[int] = 404
    type_uri: ClassVar[str] = "urn:lip:error:registry-not-found"
    title: ClassVar[str] = "Model Not Found in Registry"
    detail_template: ClassVar[str] = "Model '{model}' is not registered with this provider."

    @override
    def __init__(self, *, model: str) -> None:
        super().__init__(params=RegistryNotFoundParams(model=model))

    @override
    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        params = cast("BaseModel", self.params)
        return self.detail_template.format(**params.model_dump())
