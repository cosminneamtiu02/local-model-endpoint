"""DomainError base class — the root of all errors that cross the API boundary.

Subclasses are generated from packages/error-contracts/errors.yaml.
Do not subclass DomainError directly in application code — edit
errors.yaml and run `task errors:generate` instead.
"""

from typing import ClassVar

from pydantic import BaseModel


class DomainError(Exception):
    """Abstract base class for all domain errors.

    Each subclass has:
    - code: machine-readable error code (e.g. "NOT_FOUND")
    - http_status: HTTP status code to return
    - params: typed parameter object (or None for parameterless errors)

    Direct instantiation of `DomainError` is rejected at runtime — the
    class is only useful as a base. ABCMeta would be cleaner but
    Exception already has a metaclass, so we guard via __init__.
    """

    code: ClassVar[str]
    http_status: ClassVar[int]
    params: BaseModel | None

    def __init__(self, *, params: BaseModel | None = None) -> None:
        if type(self) is DomainError:
            msg = "DomainError is abstract; instantiate a subclass instead"
            raise TypeError(msg)
        self.params = params
        # Only expose code in exception args — never user params (PII risk).
        super().__init__(self.code)

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "code") or not hasattr(cls, "http_status"):
            msg = f"{cls.__name__} must declare ClassVar 'code: str' and 'http_status: int'"
            raise TypeError(msg)
