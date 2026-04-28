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
    - type_uri: stable URN identifying the problem type. LIP uses
      non-resolvable URNs in v1 (e.g. "urn:lip:error:not-found"), deviating
      from RFC 7807 §3.1's SHOULD-resolve guidance — a future hosted-docs
      URL mapping can be introduced without breaking the URN format.
    - title: short human-readable summary per RFC 7807 §3.1
    - detail_template: per-instance human-readable explanation; substituted via
      ``str.format(**params.model_dump())`` for parameterized errors. For
      parameterless errors the value is unused — ``detail()`` returns ``title``.
    - params: typed parameter object (or None for parameterless errors)
    - detail(): renders the per-instance detail string. Generated per subclass.
    """

    code: ClassVar[str]
    http_status: ClassVar[int]
    type_uri: ClassVar[str]
    title: ClassVar[str]
    detail_template: ClassVar[str]
    params: BaseModel | None

    def __init__(self, *, params: BaseModel | None = None) -> None:
        # DomainError is abstract — only generated subclasses (which carry the
        # required ClassVars) may be instantiated. Direct construction is a
        # programming error.
        if type(self) is DomainError:
            msg = "DomainError is abstract; instantiate a generated subclass instead."
            raise TypeError(msg)
        self.params = params
        # Only expose code in exception args — never user params (PII risk)
        super().__init__(self.code)

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        required: tuple[str, ...] = ("code", "http_status", "type_uri", "title", "detail_template")
        missing = [name for name in required if not hasattr(cls, name)]
        if missing:
            joined = ", ".join(missing)
            msg = f"{cls.__name__} must declare ClassVar fields: {joined}"
            raise TypeError(msg)

    def detail(self) -> str:
        """Render the per-instance human-readable detail.

        Subclasses generated from errors.yaml override this. The base
        implementation returns ``title`` as the most informative default if a
        subclass is constructed without overriding (e.g. a hand-rolled
        subclass — forbidden by CLAUDE.md, but kept safe).
        """
        return self.title
