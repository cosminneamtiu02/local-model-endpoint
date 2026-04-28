"""Generated from errors.yaml. Do not edit."""

from typing import TYPE_CHECKING, ClassVar, cast

from app.exceptions._generated.rate_limited_params import RateLimitedParams
from app.exceptions.base import DomainError

if TYPE_CHECKING:
    from pydantic import BaseModel


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
        params = cast("BaseModel", self.params)
        return self.detail_template.format(**params.model_dump())
