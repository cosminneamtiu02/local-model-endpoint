"""Internal validation helpers shared between sibling content variants.

Currently houses the URL-or-base64 mutual-exclusion check used by both
:class:`AudioContent` and :class:`ImageContent`. Single underscore on
the module name marks the helpers as internal-to-the-feature; consumers
import the parent value-objects, not this module.
"""

from pydantic import BaseModel


def ensure_exactly_one_url_or_base64(model: BaseModel, label: str) -> None:
    """Validate that exactly one of ``url`` or ``base64`` is set on the model.

    Raises ValueError if neither or both are populated. ``label`` is used in
    the error message to discriminate AudioContent vs ImageContent.

    Implemented via ``getattr`` rather than a structural ``Protocol`` because
    the two callers expose ``url: AnyHttpUrl | None`` (Pydantic ``Url`` type)
    and a ``Protocol`` with ``url: object | None`` is rejected by Pyright as
    type-invariant on a mutable attribute. The defended-against typo class
    (``url2`` / ``base_64``) is caught by the existing per-call test suite.
    """
    url = getattr(model, "url", None)
    base64 = getattr(model, "base64", None)
    if (url is None) == (base64 is None):
        msg = f"{label} must have exactly one of url or base64"
        raise ValueError(msg)
