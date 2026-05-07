"""Integration tests for the /health liveness endpoint.

Filename mirrors the production module ``app/api/health_router.py`` —
sibling integration tests follow the same convention
(``test_request_id_middleware.py`` ↔ ``request_id_middleware.py``,
``test_exception_handler_registry.py`` ↔ ``exception_handler_registry.py``)
so a reviewer grepping ``find tests -name 'test_<module>.py'`` from the
documented file name finds the test on the first try.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_health_returns_200(client: AsyncClient) -> None:
    """GET /health should return 200 with status ok."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
