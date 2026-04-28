"""Contract tests for the ProblemDetails wire shape (LIP-E004-F004).

The OpenAPI-spec smoke tests live in :mod:`tests.contract.test_openapi_shape`.
A real Schemathesis fuzz suite will land alongside the LIP feature router
(LIP-E001-F002) when there are operations to fuzz against.
"""

from starlette.testclient import TestClient

from app.main import app


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


def test_health_route_declares_problem_details_default_response() -> None:
    """The /health route advertises ProblemDetails on its OpenAPI ``default`` response.

    The route uses ``responses={"default": ...}`` instead of enumerating
    individual 5xx codes (``500``, ``503``). This matches the truth on the
    ground: the global exception handler in ``app/api/errors.py`` runs
    against every status code we don't enumerate, and ``/health`` itself
    is liveness-only and never raises (so listing 500/503 as endpoint-
    specific responses would imply behavior that doesn't exist).
    """
    client = TestClient(app, raise_server_exceptions=False)
    spec = client.get("/openapi.json").json()
    health = spec["paths"]["/health"]["get"]
    responses = health.get("responses", {})

    assert "default" in responses, (
        "Expected a 'default' response on /health (the project-wide error "
        f"shape), got responses keys: {sorted(responses.keys())}"
    )
    content = responses["default"].get("content", {})
    # The ProblemDetails schema must be referenced under at least one
    # media type. The route declares both ``application/json`` (FastAPI's
    # default for ``model=...``) and ``application/problem+json`` (the
    # runtime media type emitted by ``app/api/errors.py``).
    assert any("ProblemDetails" in str(media) for media in content.values()), (
        f"/health 'default' response must reference ProblemDetails, got {content}"
    )
    assert "application/problem+json" in content, (
        "Expected the runtime media type 'application/problem+json' to be "
        f"declared on /health's default response, got: {sorted(content.keys())}"
    )


def test_problem_details_response_advertises_content_language_en() -> None:
    """Any error response must carry Content-Language: en per RFC 7807 §3.1.

    The integration suite already asserts this on a typed-handler path; the
    contract tier locks it for any framework-generated error too (e.g. 404
    from a missing route).
    """
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/this-route-definitely-does-not-exist")
    assert response.status_code == 404
    assert response.headers.get("content-language") == "en"
    assert response.headers.get("content-type", "").startswith("application/problem+json")
