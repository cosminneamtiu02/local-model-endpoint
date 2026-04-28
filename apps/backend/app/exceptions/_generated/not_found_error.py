"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar

from app.exceptions.base import DomainError


class NotFoundError(DomainError):
    """Requested resource does not exist"""

    code: ClassVar[str] = "NOT_FOUND"
    http_status: ClassVar[int] = 404

    def __init__(self) -> None:
        super().__init__(params=None)
