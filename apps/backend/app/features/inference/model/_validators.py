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
    # Two-branch is_None check matches the per-leaf ``is None`` discipline
    # used elsewhere in the inference model (e.g. ollama_translation.py),
    # and surfaces the violated half ("got neither" vs "got both") instead
    # of a single generic message. CLAUDE.md sacred rule "no paradigm
    # drift" — the codebase already does explicit-leaf is-None checks.
    if url is None and base64 is None:
        msg = f"{label} must have exactly one of url or base64 (got neither)"
        raise ValueError(msg)
    if url is not None and base64 is not None:
        msg = f"{label} must have exactly one of url or base64 (got both)"
        raise ValueError(msg)
