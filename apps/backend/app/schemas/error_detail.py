"""Error detail schema — a single validation error."""

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    """A single validation error detail."""

    model_config = ConfigDict(extra="forbid")

    field: str
    reason: str
