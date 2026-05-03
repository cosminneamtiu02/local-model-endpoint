"""Generated from errors.yaml. Do not edit."""

from typing import ClassVar, cast, override

from app.exceptions._generated.queue_full_params import QueueFullParams
from app.exceptions.base import DomainError


class QueueFullError(DomainError):
    """Inference queue at capacity, request rejected (LIP-E004-F002)"""

    code: ClassVar[str] = "QUEUE_FULL"
    http_status: ClassVar[int] = 503
    type_uri: ClassVar[str] = "urn:lip:error:queue-full"
    title: ClassVar[str] = "Inference Queue Full"
    detail_template: ClassVar[str] = (
        "Inference queue at capacity ({current_waiters} waiters, max {max_waiters})."
    )

    @override
    def __init__(self, *, max_waiters: int, current_waiters: int) -> None:
        super().__init__(
            params=QueueFullParams(
                max_waiters=max_waiters,
                current_waiters=current_waiters,
            ),
        )

    @override
    def detail(self) -> str:
        """Render the human-readable detail for this error."""
        params = cast("QueueFullParams", self.params)
        return self.detail_template.format(**params.model_dump())
