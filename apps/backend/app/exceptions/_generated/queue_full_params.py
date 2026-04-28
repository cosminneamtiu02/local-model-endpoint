"""Generated from errors.yaml. Do not edit."""

from pydantic import BaseModel, ConfigDict


class QueueFullParams(BaseModel):
    """Parameters for QUEUE_FULL error."""

    model_config = ConfigDict(extra="forbid")

    max_waiters: int
    current_waiters: int
