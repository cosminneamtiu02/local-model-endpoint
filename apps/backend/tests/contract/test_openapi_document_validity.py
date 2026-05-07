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

from typing import TYPE_CHECKING, Any

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


def test_openapi_info_publishes_version_contact_and_license(
    openapi_spec: dict[str, Any],
) -> None:
    """The OpenAPI ``info`` block carries version, contact, and license metadata.

    SDK codegen tools (openapi-typescript, openapi-generator) read these
    fields to stamp generated client packages. ``app/main.py`` deliberately
    wires them via the elaborate ``_AppVersionResolution`` subsystem +
    explicit constructor kwargs; without this canary, a regression
    dropping ``_APP_VERSION`` (e.g. an accidental ``version="0.1.0"``
    literal) would only show up downstream in consumer SDK regen.
    """
    from app.main import _APP_VERSION

    info = openapi_spec["info"]
    assert info["version"] == _APP_VERSION, (
        f"OpenAPI info.version must reflect the resolved app version "
        f"(_APP_VERSION); got info.version={info['version']!r}, "
        f"_APP_VERSION={_APP_VERSION!r}"
    )
    assert info["contact"] == {"name": "Cosmin Neamtiu"}, (
        f"OpenAPI info.contact must match app/main.py's contact pin; got {info.get('contact')!r}"
    )
    assert info["license"] == {"name": "MIT", "identifier": "MIT"}, (
        f"OpenAPI info.license must match app/main.py's license_info pin; "
        f"got {info.get('license')!r}"
    )


def test_openapi_components_publishes_problem_details_and_health_response(
    openapi_spec: dict[str, Any],
) -> None:
    """``components.schemas`` carries the project's two wire-shape components.

    A regression that mis-published either component (a ``response_model=``
    swap, a typo in a per-route ``responses=`` map) would show up as an
    SDK-codegen warning downstream; the canary catches it at PR time.
    """
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    assert "ProblemDetails" in schemas, (
        f"ProblemDetails must be in components.schemas; got: {sorted(schemas.keys())}"
    )
    assert "HealthResponse" in schemas, (
        f"HealthResponse must be in components.schemas; got: {sorted(schemas.keys())}"
    )
