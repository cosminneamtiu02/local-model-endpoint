"""Contract tests for the ProblemDetails COMPONENT shape (LIP-E004-F004).

Strictly per-component shape concerns: the ``ProblemDetails`` schema's
publication, RFC 7807 field set, and ``additionalProperties`` declaration.
Per-route publication concerns (``/health``'s ``responses.default``
content map; framework-404 RFC 7807 wire shape) live in
:mod:`tests.contract.test_health_route_publication`. The OpenAPI-document
smoke tests live in :mod:`tests.contract.test_openapi_document_validity`.

A real Schemathesis fuzz suite will land alongside the LIP feature router
(LIP-E001-F002) when there are operations to fuzz against.

Uses the per-test ``client`` fixture from ``tests/contract/conftest.py``
so each test sees a freshly-built FastAPI instance with the autouse
Settings-env scrub applied.
"""

from fastapi.testclient import TestClient


def test_openapi_publishes_problem_details_component(client: TestClient) -> None:
    """ProblemDetails appears as a named component once a route references it."""
    spec = client.get("/openapi.json").json()
    schemas = spec.get("components", {}).get("schemas", {})
    assert "ProblemDetails" in schemas, (
        "ProblemDetails must be in components.schemas — it is the "
        "F004 contract surface other features build on."
    )


def test_problem_details_component_has_rfc7807_fields_and_extensions(client: TestClient) -> None:
    """All five RFC 7807 standard fields plus code + request_id appear in the schema."""
    spec = client.get("/openapi.json").json()
    pd_schema = spec["components"]["schemas"]["ProblemDetails"]
    properties = pd_schema.get("properties", {})

    # RFC 7807 standard fields
    for field in ("type", "title", "status", "detail", "instance"):
        assert field in properties, f"Missing RFC 7807 field: {field}"
    # LIP project extensions
    for field in ("code", "request_id"):
        assert field in properties, f"Missing LIP extension: {field}"


def test_problem_details_component_allows_additional_properties(client: TestClient) -> None:
    """extra='allow' must serialize to additionalProperties: true (or schema)."""
    spec = client.get("/openapi.json").json()
    pd_schema = spec["components"]["schemas"]["ProblemDetails"]
    additional = pd_schema.get("additionalProperties")
    # Pydantic v2 emits either True or a schema dict for extra='allow'
    assert additional is True or isinstance(additional, dict), (
        f"ProblemDetails must declare additionalProperties; got {additional!r}"
    )
