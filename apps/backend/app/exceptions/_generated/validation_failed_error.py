"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar

from app.exceptions._generated.validation_failed_params import ValidationFailedParams
from app.exceptions.base import DomainError


class ValidationFailedError(DomainError):
    """Error: VALIDATION_FAILED."""

    code: ClassVar[str] = "VALIDATION_FAILED"
    http_status: ClassVar[int] = 422
    type_uri: ClassVar[str] = "urn:lip:error:validation-failed"
    title: ClassVar[str] = "Validation Failed"
    detail_template: ClassVar[str] = "Validation failed for field '{field}': {reason}"

    def __init__(self, *, field: str, reason: str) -> None:
        super().__init__(params=ValidationFailedParams(field=field, reason=reason))

    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        assert self.params is not None  # parameterized error
        return self.detail_template.format(**self.params.model_dump())
