"""Registry of feature routers.

main.py imports ``register_routers`` here, never directly from
``features/``. New features add their entries below as they land —
main.py stays unchanged feature after feature. The lifespan-managed
resource factory ``lifespan_resources`` lives in the sibling
``lifespan_resources.py`` module so each ``*_registry.py`` file is
single-purpose (mirroring ``exception_handler_registry.py``).
"""

from fastapi import FastAPI

from app.api.health_router import health_router

__all__ = ["register_routers"]


def register_routers(application: FastAPI) -> None:
    """Mount every router on the FastAPI app.

    Health stays at root (unversioned, liveness/readiness conventions).
    Feature routers nest under ``/v1`` once any are added; mount them
    here via ``application.include_router(feature_router, prefix="/v1")``
    so the prefix is centrally owned (each feature router declares only
    its sub-path, not the version segment).

    Forward registration-order convention (LIP-E001-F002 onward): health/
    readyz routers register first, feature routers after. All feature
    routers mount under ``/v1`` so the OpenAPI operation listing stays
    stable across SDK regenerations. The future inference router will
    declare its sub-path (e.g. ``/inference/chat``) without the version
    segment, and the ``prefix="/v1"`` here owns the version namespace.

    Forward operation_id convention: ``getHealth`` (camelCase verb-noun)
    is the precedent. New routes follow the same shape — ``createChat``,
    ``getModels``, etc. SDK codegen tools (openapi-typescript) emit
    method names from ``operationId``; pinning the convention before a
    second route lands removes the bikeshed cycle.
    """
    application.include_router(health_router)
