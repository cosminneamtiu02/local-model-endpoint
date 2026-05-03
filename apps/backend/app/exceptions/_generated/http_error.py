"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar, override

from app.exceptions.base import DomainError


class HttpError(DomainError):
    """Generic HTTP-level error raised through the StarletteHTTPException path"""

    code: ClassVar[str] = "HTTP_ERROR"
    http_status: ClassVar[int] = 400
    type_uri: ClassVar[str] = "urn:lip:error:http-error"
    title: ClassVar[str] = "HTTP Error"
    detail_template: ClassVar[str] = "An HTTP-level error occurred while processing the request."

    @override
    def __init__(self) -> None:
        super().__init__(params=None)

    @override
    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        return self.detail_template
