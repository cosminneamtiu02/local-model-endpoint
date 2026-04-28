"""Error body schema — the error object inside the response."""

from pydantic import BaseModel, ConfigDict

from app.schemas.error_detail import ErrorDetail


class ErrorBody(BaseModel):
    """The error object inside the response."""

    model_config = ConfigDict(extra="forbid")

    code: str
    params: dict[str, str | int | float | bool]
    details: list[ErrorDetail] | None = None
    request_id: str
