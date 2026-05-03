"""Shared test helpers — assertion shortcuts that would otherwise drift across files.

Imported by tests in both `tests/unit/exceptions/` and `tests/integration/` so
the four canonical RFC 7807 wire-shape invariants (status, content-type, code,
content-language) are pinned in exactly one place. Adding a fifth invariant
(or relaxing an existing one) is a single edit instead of a 17-callsite sweep.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import Response


def assert_problem_json_envelope(response: Response, *, status: int, code: str) -> None:
    """Assert the four canonical RFC 7807 envelope invariants on a response.

    - HTTP status matches.
    - Content-Type is ``application/problem+json; charset=utf-8`` (the
      LIP-pinned form, not the bare ``application/problem+json`` RFC 7807
      §3 permits).
    - Content-Language is ``en`` (LIP v1's i18n contract).
    - Body carries the LIP-extension ``code`` matching the typed error.
    - Body carries a ``request_id`` (correlation handle).
    """
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json; charset=utf-8"
    assert response.headers["content-language"] == "en"
    body = response.json()
    assert body["code"] == code
    assert "request_id" in body
