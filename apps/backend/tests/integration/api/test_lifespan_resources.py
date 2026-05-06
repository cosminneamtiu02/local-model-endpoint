"""Integration tests for :mod:`app.api.lifespan_resources` and :class:`AppState`.

Mirrors the source path ``app/api/lifespan_resources.py`` (with adjacent
coverage of ``app/api/app_state.py``) — api-layer integration concerns live
under ``tests/integration/api/``, alongside ``test_health_router.py`` and
``test_request_id_middleware.py``. The OllamaClient round-trip /
``chat()`` integration tests live at
``tests/integration/features/inference/repository/test_ollama_client.py``.
"""

from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.deps import get_ollama_client
from app.features.inference import OllamaClient


def test_lifespan_constructs_and_closes_client_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lifespan wires exactly one ``OllamaClient`` __init__ and one ``close``."""
    from app.features.inference.repository import ollama_client as oc_mod
    from app.main import create_app

    init_count = 0
    close_count = 0
    original_init = oc_mod.OllamaClient.__init__
    original_close = oc_mod.OllamaClient.close

    def counting_init(
        self: OllamaClient,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal init_count
        init_count += 1
        # ``*args/**kwargs: object`` matches the original __init__'s typed
        # surface positionally; pyright cannot see the structural match
        # through the ``object`` spread, hence the suppression below.
        original_init(self, *args, **kwargs)  # pyright: ignore[reportArgumentType]

    async def counting_close(self: OllamaClient) -> None:
        nonlocal close_count
        close_count += 1
        await original_close(self)

    monkeypatch.setattr(oc_mod.OllamaClient, "__init__", counting_init)
    monkeypatch.setattr(oc_mod.OllamaClient, "close", counting_close)

    app = create_app()
    with TestClient(app):
        # entering and exiting the context manager triggers lifespan
        # startup + shutdown
        pass

    assert init_count == 1
    assert close_count == 1


def test_app_state_client_survives_across_requests() -> None:
    """``app.state.context.ollama_client`` identity holds across requests (ADR-012)."""
    from app.main import create_app

    app = create_app()

    @app.get("/_test/ollama_client_id")
    async def echo_client_id(
        client: Annotated[OllamaClient, Depends(get_ollama_client)],
    ) -> dict[str, int]:
        return {"id": id(client)}

    with TestClient(app) as test_client:
        r1 = test_client.get("/_test/ollama_client_id")
        r2 = test_client.get("/_test/ollama_client_id")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


async def test_lifespan_close_runs_even_when_yield_body_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8: lifespan finally: must close the client even if the app body raises.

    Drives the lifespan context manager directly so we can inject an
    exception at the yield point (the "app body" in the spec's wording).
    The TestClient route-handler path can't reproduce this — FastAPI
    catches request-handler exceptions before they reach the lifespan
    generator; we need to raise into the async-with body itself.
    """
    from app.features.inference.repository import ollama_client as oc_mod
    from app.main import create_app, lifespan

    close_count = 0
    original_close = oc_mod.OllamaClient.close

    async def counting_close(self: OllamaClient) -> None:
        nonlocal close_count
        close_count += 1
        await original_close(self)

    monkeypatch.setattr(oc_mod.OllamaClient, "close", counting_close)

    app = create_app()
    boom = "simulated app-body failure"
    with pytest.raises(RuntimeError, match=boom):
        async with lifespan(app):
            raise RuntimeError(boom)

    assert close_count == 1
