"""Contract tests — validates OpenAPI spec compliance.

The spec-shape test below always runs as the canary for "did the
OpenAPI even generate correctly." A full Schemathesis fuzz test will
be added once the LIP feature router (LIP-E001-F002) lands and there
are operations to fuzz against.
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

    # Health endpoint at root, outside /api/v1/
    assert "/health" in paths

    # The LIP feature router will add inference paths under /api/v1/
    # when LIP-E001-F002 lands during feature-dev. Pre-feature-dev,
    # /api/v1/ has no operations and is not present in the spec.


def test_health_endpoint_conforms_to_spec() -> None:
    """Health endpoint should return the expected shape."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ── LIP-E004-F004: ProblemDetails contract ────────────────────────────────


def test_openapi_publishes_problem_details_component() -> None:
    """ProblemDetails appears as a named component once a route references it."""
    client = TestClient(app, raise_server_exceptions=False)
    spec = client.get("/openapi.json").json()
    schemas = spec.get("components", {}).get("schemas", {})
    assert "ProblemDetails" in schemas, (
        "ProblemDetails must be in components.schemas — it is the "
        "F004 contract surface other features build on."
    )


def test_problem_details_component_has_rfc7807_fields_and_extensions() -> None:
    """All five RFC 7807 standard fields plus code + request_id appear in the schema."""
    client = TestClient(app, raise_server_exceptions=False)
    spec = client.get("/openapi.json").json()
    pd_schema = spec["components"]["schemas"]["ProblemDetails"]
    properties = pd_schema.get("properties", {})

    # RFC 7807 standard fields
    for field in ("type", "title", "status", "detail", "instance"):
        assert field in properties, f"Missing RFC 7807 field: {field}"
    # LIP project extensions
    for field in ("code", "request_id"):
        assert field in properties, f"Missing LIP extension: {field}"


def test_problem_details_component_allows_additional_properties() -> None:
    """extra='allow' must serialize to additionalProperties: true (or schema)."""
    client = TestClient(app, raise_server_exceptions=False)
    spec = client.get("/openapi.json").json()
    pd_schema = spec["components"]["schemas"]["ProblemDetails"]
    additional = pd_schema.get("additionalProperties")
    # Pydantic v2 emits either True or a schema dict for extra='allow'
    assert additional is True or isinstance(additional, dict), (
        f"ProblemDetails must declare additionalProperties; got {additional!r}"
    )


def test_health_route_declares_problem_details_for_5xx_responses() -> None:
    """The /health route advertises ProblemDetails on its 5xx responses."""
    client = TestClient(app, raise_server_exceptions=False)
    spec = client.get("/openapi.json").json()
    health = spec["paths"]["/health"]["get"]
    responses = health.get("responses", {})
    for status in ("500", "503"):
        assert status in responses
        content = responses[status].get("content", {})
        # FastAPI/Pydantic emits the schema under application/json by default;
        # the runtime Content-Type is overridden to application/problem+json
        # by the handler. The contract here is "the schema is referenced".
        assert any("ProblemDetails" in str(media) for media in content.values()), (
            f"/health 5xx response must reference ProblemDetails, got {content}"
        )
