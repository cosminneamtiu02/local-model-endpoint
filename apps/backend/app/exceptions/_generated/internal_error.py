"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar, override

from app.exceptions.base import DomainError


class InternalError(DomainError):
    """Unhandled server error, details are logged with request_id"""

    code: ClassVar[str] = "INTERNAL_ERROR"
    http_status: ClassVar[int] = 500
    type_uri: ClassVar[str] = "urn:lip:error:internal-error"
    title: ClassVar[str] = "Internal Server Error"
    detail_template: ClassVar[str] = (
        "An unexpected error occurred. Use the request_id to correlate with server logs."
    )

    @override
    def __init__(self) -> None:
        super().__init__(params=None)

    @override
    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        return self.detail_template
