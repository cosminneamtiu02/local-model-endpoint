"""Lifecycle-managed httpx.AsyncClient wrapper for talking to Ollama."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Literal, Self

import httpx

from app.features.inference.repository.ollama_translation import (
    build_chat_result,
    translate_message,
    translate_params,
)

if TYPE_CHECKING:
    from types import TracebackType

    from app.features.inference.model.message import Message
    from app.features.inference.model.model_params import ModelParams
    from app.features.inference.model.ollama_chat_result import OllamaChatResult

# 600s read timeout is a defense-in-depth backstop until LIP-E004-F003 lands a
# per-request ``asyncio.wait_for`` around the ``chat`` call. With ``read=None``
# the only release path for a hung Ollama daemon is killing the process — a
# self-inflicted DoS surface for a service guarded by a single semaphore slot.
# 600s is generous enough not to interrupt legitimate long-running thinking-mode
# inference under Gemma 4 while still bounding the worst case.
DEFAULT_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(
    connect=5.0,
    read=600.0,
    write=None,
    pool=None,
)

# HTTP verbs the adapter actually uses against Ollama. Narrowed at the
# `_request` boundary so a typo (`"PSOT"`) is a static error, not a 405
# at runtime. Add a verb here only when a new adapter method needs it.
type HttpMethod = Literal["GET", "POST"]


class OllamaClient:
    """Lifecycle-managed httpx.AsyncClient for talking to Ollama.

    Constructed at app lifespan startup; closed at lifespan shutdown.
    Sibling feature LIP-E003-F003 (failure mapping) wraps `chat()` to
    convert httpx exceptions into typed DomainError subclasses; the
    private `_request` method is the lower-level seam other adapter
    methods (e.g. future `/api/embeddings`) would build on top of from
    *within* this class. External callers must go through `chat` (or
    a future typed sibling) — `_client` and `_request` are
    single-underscore by convention and `SLF001`-enforced for non-test
    code.

    The class name keeps the "Client" suffix (not "Repository") because
    the role is HTTP-client wrapping; CLAUDE.md's example of
    `OllamaRepository` is a guide, not an absolute rule.
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
        """Close the underlying httpx.AsyncClient. Idempotent."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        """Enter async context manager; returns self for `async with` binding."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit async context manager; closes the underlying client."""
        del exc_type, exc, tb  # exception state surfaced by close() / await chain
        await self.close()

    async def _request(
        self,
        method: HttpMethod,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Low-level passthrough to httpx — used by sibling adapter features."""
        return await self._client.request(method, path, json=json)

    async def chat(
        self,
        *,
        model_tag: str,
        messages: list[Message],
        params: ModelParams,
    ) -> OllamaChatResult:
        """Translate envelope -> Ollama /api/chat -> OllamaChatResult.

        `model_tag` is the registry-resolved backend tag (the
        orchestrator does the logical-name lookup before calling).
        `params` is already merged over registry defaults by E002-F002.
        F002 owns only the wire translation; failure mapping (httpx
        exceptions -> typed DomainError) lives in F003 and wraps this
        method.
        """
        # Field order intentionally mirrors the spec acceptance-criterion
        # example body (model, messages, options, stream) so wire dumps
        # are reviewable side-by-side with graphs/LIP/LIP-E003-F002.md.
        body: dict[str, Any] = {
            "model": model_tag,
            "messages": [translate_message(m) for m in messages],
        }
        options = translate_params(params)
        if options:
            body["options"] = options
        body["stream"] = False
        if params.think:
            # [UNRESOLVED] LIP-E003-F002: top-level placement is the
            # spec's tentative pattern for Gemma 4 thinking mode;
            # verify against the running daemon when E005-F001 warm-up
            # first exercises this path.
            body["think"] = True

        response = await self._request("POST", "/api/chat", json=body)
        response.raise_for_status()
        return build_chat_result(response.json())
