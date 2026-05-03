"""Contract-level OpenAPI shape assertions.

These run as the canary for "did the OpenAPI even generate correctly."
The full Schemathesis fuzz across endpoints arrives with LIP-E001-F002; this file exercises
the spec endpoints directly so mis-shaped output is caught before fuzz
attempts to load it.
"""

from starlette.testclient import TestClient

from app.main import app


def test_openapi_spec_is_valid() -> None:
    """The OpenAPI spec should be valid and contain the expected endpoints."""
    client = TestClient(app, raise_server_exceptions=False)
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


def test_health_endpoint_conforms_to_spec() -> None:
    """Health endpoint should return the expected shape."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
