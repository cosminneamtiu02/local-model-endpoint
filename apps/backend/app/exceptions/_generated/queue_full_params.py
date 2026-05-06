"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class QueueFullParams(BaseModel):
    """Parameters for QUEUE_FULL error.

    Inference queue at capacity, request rejected (LIP-E004-F002).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_waiters: int
    current_waiters: int
