"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar, override

from app.exceptions.base import DomainError


class MethodNotAllowedError(DomainError):
    """Request used an HTTP method the route does not accept"""

    code: ClassVar[str] = "METHOD_NOT_ALLOWED"
    http_status: ClassVar[int] = 405
    type_uri: ClassVar[str] = "urn:lip:error:method-not-allowed"
    title: ClassVar[str] = "Method Not Allowed"
    detail_template: ClassVar[str] = "The HTTP method used is not allowed for this route."

    @override
    def __init__(self) -> None:
        super().__init__(params=None)

    @override
    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        return self.detail_template
