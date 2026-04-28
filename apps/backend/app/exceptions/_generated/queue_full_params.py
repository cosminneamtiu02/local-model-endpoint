"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel


class QueueFullParams(BaseModel):
    """Parameters for QUEUE_FULL error."""

    max_waiters: int
    current_waiters: int
