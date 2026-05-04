"""Contract-level OpenAPI shape assertions.

These run as the canary for "did the OpenAPI even generate correctly."
The full Schemathesis fuzz across endpoints arrives with LIP-E001-F002; this file exercises
the spec endpoints directly so mis-shaped output is caught before fuzz
attempts to load it.

Uses the per-test ``client`` fixture from ``tests/contract/conftest.py``
(rather than the module-singleton ``app.main:app``) so the autouse
Settings-env scrub in the root conftest takes effect — symmetric with
the integration tier's hermeticity policy.
"""

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
