"""Lifecycle-managed httpx.AsyncClient wrapper for talking to Ollama."""

from __future__ import annotations

from typing import Any, Final, Self

import httpx

DEFAULT_TIMEOUT: Final = httpx.Timeout(connect=5.0, read=None, write=None, pool=None)


class OllamaClient:
    """Lifecycle-managed httpx.AsyncClient for talking to Ollama.

    Constructed at app lifespan startup; closed at lifespan shutdown.
    Sibling features (LIP-E003-F002 translation, LIP-E003-F003 failure
    mapping) call the low-level _request method; direct _client access
    is permitted only when the wrapper genuinely needs more httpx
    surface than _request provides.
    """

    def __init__(
        self,
        base_url: str,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # transport kwarg is a test seam: integration tests inject
        # httpx.MockTransport to verify _request plumbing without a
        # live Ollama. Production call sites pass no transport, so
        # httpx uses its default AsyncHTTPTransport with the configured
        # connection-pool limits.
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await self._client.request(method, path, json=json)
