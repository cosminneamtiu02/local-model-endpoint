"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar, cast, override

from app.exceptions._generated.rate_limited_params import RateLimitedParams
from app.exceptions.base import DomainError


class RateLimitedError(DomainError):
    """Client exceeded rate limit"""

    code: ClassVar[str] = "RATE_LIMITED"
    http_status: ClassVar[int] = 429
    type_uri: ClassVar[str] = "urn:lip:error:rate-limited"
    title: ClassVar[str] = "Too Many Requests"
    detail_template: ClassVar[str] = (
        "Rate limit exceeded. Retry after {retry_after_seconds} seconds."
    )

    @override
    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__(params=RateLimitedParams(retry_after_seconds=retry_after_seconds))

    @override
    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        params = cast("RateLimitedParams", self.params)
        return self.detail_template.format(**params.model_dump())
