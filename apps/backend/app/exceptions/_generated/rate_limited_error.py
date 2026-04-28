"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar

from app.exceptions._generated.rate_limited_params import RateLimitedParams
from app.exceptions.base import DomainError


class RateLimitedError(DomainError):
    """Error: RATE_LIMITED."""

    code: ClassVar[str] = "RATE_LIMITED"
    http_status: ClassVar[int] = 429
    type_uri: ClassVar[str] = "urn:lip:error:rate-limited"
    title: ClassVar[str] = "Too Many Requests"
    detail_template: ClassVar[str] = (
        "Rate limit exceeded. Retry after {retry_after_seconds} seconds."
    )

    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__(params=RateLimitedParams(retry_after_seconds=retry_after_seconds))

    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        assert self.params is not None  # parameterized error
        return self.detail_template.format(**self.params.model_dump())
