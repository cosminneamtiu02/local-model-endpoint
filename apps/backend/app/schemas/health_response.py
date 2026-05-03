"""Health response schema."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Liveness probe response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = Field(
        default="ok",
        description="Liveness sentinel; constant 'ok' when the process is up.",
    )
