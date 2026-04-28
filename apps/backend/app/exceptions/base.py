"""DomainError base class — the root of all errors that cross the API boundary.

Subclasses are generated from packages/error-contracts/errors.yaml.
Do not subclass DomainError directly in application code — edit errors.yaml
and run `task errors:generate` instead.
"""

from typing import ClassVar

from pydantic import BaseModel


class DomainError(Exception):
    """Base class for all domain errors.

    Each subclass has:
    - code: machine-readable error code (e.g. "NOT_FOUND")
    - http_status: HTTP status code to return
    - params: typed parameter object (or None for parameterless errors)
    """

    code: ClassVar[str]
    http_status: ClassVar[int]
    params: BaseModel | None

    def __init__(self, *, params: BaseModel | None = None) -> None:
        self.params = params
        # Only expose code in exception args — never user params (PII risk)
        super().__init__(self.code)

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "code") or not hasattr(cls, "http_status"):
            msg = f"{cls.__name__} must declare ClassVar 'code' and 'http_status'"
            raise TypeError(msg)
