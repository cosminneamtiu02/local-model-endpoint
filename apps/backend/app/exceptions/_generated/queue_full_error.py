"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar

from app.exceptions._generated.queue_full_params import QueueFullParams
from app.exceptions.base import DomainError


class QueueFullError(DomainError):
    """Error: QUEUE_FULL."""

    code: ClassVar[str] = "QUEUE_FULL"
    http_status: ClassVar[int] = 503
    type_uri: ClassVar[str] = "urn:lip:error:queue-full"
    title: ClassVar[str] = "Inference Queue Full"
    detail_template: ClassVar[str] = (
        "Inference queue at capacity ({current_waiters} waiters, max {max_waiters})."
    )

    def __init__(self, *, max_waiters: int, current_waiters: int) -> None:
        super().__init__(
            params=QueueFullParams(
                max_waiters=max_waiters,
                current_waiters=current_waiters,
            ),
        )

    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        assert self.params is not None  # parameterized error
        return self.detail_template.format(**self.params.model_dump())
