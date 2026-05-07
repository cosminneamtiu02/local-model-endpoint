"""Internal validation helpers shared by sibling content variants.

Houses the URL-or-base64 mutual-exclusion check used by ``AudioContent``
and ``ImageContent``. The leading-underscore module name marks the
helpers as internal-to-the-feature: imported only by sibling files
within ``app.features.inference.model``. Not part of the model layer's
public surface; CLAUDE.md sacred-rule discipline + the leading-
underscore convention is the safeguard against a sibling layer
(``repository`` / ``schemas`` / future ``router``) shortcutting through
this module.

FORWARD: the current ``ensure_exactly_one_url_or_base64(model, label)``
helper takes a ``BaseModel`` and reaches for ``getattr(model, "url",
None)`` because a typed ``Protocol`` carrying ``url: object | None`` is
rejected by Pyright as type-invariant on a mutable attribute. A future
refactor can replace the ``getattr`` indirection with explicit keyword-
only ``url`` and ``base64`` args (``def ensure_exactly_one_url_or_base64(
*, url: object | None, base64: object | None, label: str)``), letting
Pyright narrow at each call site and removing one runtime introspection.
The present shape works; the refactor is ergonomic-only.
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
