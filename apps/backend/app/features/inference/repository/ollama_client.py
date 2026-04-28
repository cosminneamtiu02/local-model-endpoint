"""Lifecycle-managed httpx.AsyncClient wrapper for talking to Ollama."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

import httpx

if TYPE_CHECKING:
    from types import TracebackType

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=None, pool=None)


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
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await self._client.request(method, path, json=json)
