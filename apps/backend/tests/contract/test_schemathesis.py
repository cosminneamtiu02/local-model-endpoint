"""Schemathesis fuzz of the auto-generated OpenAPI spec.

Loads the spec from a freshly-built ASGI app and parametrizes a single
test function over every operation Schemathesis discovers. Pre-feature-
dev, only /health is registered; once LIP-E001-F002 lands, /v1/inference
becomes the primary fuzz target.

The 4.x API uses `schema.parametrize()` as the operation-level
parametrization decorator and `case.call_and_validate()` to call the
ASGI app and validate the response against the schema in one step.
"""

from __future__ import annotations

import schemathesis

from app.main import create_app

# Build the app once at module import; from_asgi reads /openapi.json
# through the ASGI transport (no real network).
_app = create_app()
schema = schemathesis.openapi.from_asgi("/openapi.json", _app)


@schema.parametrize()
def test_openapi_operations_pass_default_checks(case: schemathesis.Case) -> None:
    """Every discovered operation must round-trip and validate against the schema.

    `call_and_validate` issues the request through Schemathesis's ASGI
    transport (so no real network) and runs the default check set, which
    includes status-code conformance, content-type conformance, and
    response-schema conformance.
    """
    case.call_and_validate()
