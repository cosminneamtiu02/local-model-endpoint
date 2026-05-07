"""Contract-level OpenAPI DOCUMENT-validity assertions.

These run as the canary for "did the OpenAPI even generate correctly."
Per-component shape concerns (``ProblemDetails`` fields, additional
properties) live in :mod:`tests.contract.test_problem_details_shape`;
per-route publication concerns (e.g. ``/health``'s
``responses.default`` content map and the framework-404 RFC 7807 wire
shape) live in :mod:`tests.contract.test_health_route_publication`.
This file is strictly document-level: "does the OpenAPI document parse
and carry the expected envelope keys."

The full Schemathesis fuzz across endpoints arrives with LIP-E001-F002;
this file exercises the spec endpoints directly so mis-shaped output is
caught before fuzz attempts to load it.

Uses the per-test ``client`` fixture from ``tests/contract/conftest.py``
(rather than the module-singleton ``app.main:app``) so the autouse
Settings-env scrub in the root conftest takes effect — symmetric with
the integration tier's hermeticity policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_openapi_spec_is_valid(client: TestClient) -> None:
    """The OpenAPI spec should be valid and contain the expected endpoints."""
    response = client.get("/openapi.json")
    assert response.status_code == 200

    spec = response.json()
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"] == "Local Inference Provider"

    paths = spec["paths"]

    # Health endpoint at root, outside /v1/
    assert "/health" in paths

    # The LIP feature router will add inference paths under /v1/
    # when LIP-E001-F002 lands during feature-dev. Pre-feature-dev,
    # /v1/ has no operations and is not present in the spec.
