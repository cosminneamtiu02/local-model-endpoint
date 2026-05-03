"""Shared test helpers — assertion shortcuts that would otherwise drift across files.

Imported by tests in both `tests/unit/exceptions/` and `tests/integration/` so
the canonical RFC 7807 wire-shape invariants (status, content-type, code,
content-language, optionally request_id correlation) are pinned in exactly one
place. Adding a new invariant (or relaxing an existing one) is a single edit
instead of a 17-callsite sweep.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from httpx import Response


def assert_problem_json_envelope(
    response: Response,
    *,
    status: int,
    code: str,
    check_request_id_correlation: bool = False,
) -> dict[str, Any]:
    """Assert the canonical RFC 7807 envelope invariants on a response.

    Always-checked invariants:
      1. HTTP status matches.
      2. Content-Type is ``application/problem+json; charset=utf-8`` (the
         LIP-pinned form, not the bare ``application/problem+json`` RFC 7807
         §3 permits).
      3. Content-Language is ``en`` (LIP v1's i18n contract).
      4. Body carries the LIP-extension ``code`` matching the typed error.
      5. Body carries a ``request_id`` (correlation handle).

    Optional invariant (``check_request_id_correlation=True``):
      6. Body's ``request_id`` matches the ``X-Request-ID`` response header
         (correlation contract — middleware ↔ handler).

    Returns the parsed body so the call site can make code-specific
    follow-up assertions.
    """
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json; charset=utf-8"
    assert response.headers["content-language"] == "en"
    body = response.json()
    assert body["code"] == code
    assert "request_id" in body
    if check_request_id_correlation:
        assert body["request_id"] == response.headers["X-Request-ID"]
    return body
