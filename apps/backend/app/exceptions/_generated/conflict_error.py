"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar, override

from app.exceptions.base import DomainError


class ConflictError(DomainError):
    """Operation conflicts with current state."""

    code: ClassVar[str] = "CONFLICT"
    http_status: ClassVar[int] = 409
    type_uri: ClassVar[str] = "urn:lip:error:conflict"
    title: ClassVar[str] = "Conflict"
    detail_template: ClassVar[str] = "The operation conflicts with the current resource state."

    @override
    def __init__(self) -> None:
        super().__init__(params=None)

    @override
    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        return self.detail_template
