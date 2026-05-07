"""Contract tests for the /health route's OpenAPI publication shape.

These tests describe per-ROUTE concerns (vs the per-COMPONENT
``ProblemDetails`` shape tests in
:mod:`tests.contract.test_problem_details_shape`, and vs the
DOCUMENT-level OpenAPI smoke in
:mod:`tests.contract.test_openapi_document_validity`):

* The route's OpenAPI ``responses.default`` content map advertises the
  RFC 7807 ``application/problem+json`` media type and references the
  ``ProblemDetails`` component.
* A framework-emitted 404 (request to a route the spec does not
  publish) carries ``Content-Language: en`` and
  ``application/problem+json`` per RFC 7807 §3.1 — the wire-side
  observation of the route-level OpenAPI publication contract.

Uses the per-test ``client`` fixture from ``tests/contract/conftest.py``
so each test sees a freshly-built FastAPI instance with the autouse
Settings-env scrub applied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_health_route_declares_problem_details_default_response(client: TestClient) -> None:
    """The /health route advertises ProblemDetails on its OpenAPI ``default`` response.

    The route uses ``responses={"default": ...}`` instead of enumerating
    individual 5xx codes (``500``, ``503``). This matches the truth on the
    ground: the global exception handler in ``app/api/exception_handler_registry.py`` runs
    against every status code we don't enumerate, and ``/health`` itself
    is liveness-only and never raises (so listing 500/503 as endpoint-
    specific responses would imply behavior that doesn't exist).
    """
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
    # runtime media type emitted by ``app/api/exception_handler_registry.py``).
    assert any("ProblemDetails" in str(media) for media in content.values()), (
        f"/health 'default' response must reference ProblemDetails, got {content}"
    )
    assert "application/problem+json" in content, (
        "Expected the runtime media type 'application/problem+json' to be "
        f"declared on /health's default response, got: {sorted(content.keys())}"
    )


def test_problem_details_response_advertises_content_language_en(client: TestClient) -> None:
    """Any error response must carry Content-Language: en per RFC 7807 §3.1.

    The integration suite already asserts this on a typed-handler path; the
    contract tier locks it for any framework-generated error too (e.g. 404
    from a missing route).
    """
    response = client.get("/this-route-definitely-does-not-exist")
    assert response.status_code == 404
    assert response.headers.get("content-language") == "en"
    assert response.headers.get("content-type", "").startswith("application/problem+json")
