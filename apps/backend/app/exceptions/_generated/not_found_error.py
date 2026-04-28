"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar

from app.exceptions.base import DomainError


class NotFoundError(DomainError):
    """Requested resource does not exist"""

    code: ClassVar[str] = "NOT_FOUND"
    http_status: ClassVar[int] = 404
    type_uri: ClassVar[str] = "urn:lip:error:not-found"
    title: ClassVar[str] = "Resource Not Found"
    detail_template: ClassVar[str] = "The requested resource does not exist."

    def __init__(self) -> None:
        super().__init__(params=None)

    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        return self.detail_template
