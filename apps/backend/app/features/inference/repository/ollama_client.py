"""Lifecycle-managed httpx.AsyncClient wrapper for talking to Ollama."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Literal, Self

import httpx
import structlog

from app.features.inference.repository.ollama_translation import (
    build_chat_result,
    translate_message,
    translate_params,
)

logger = structlog.get_logger(__name__)

# Identifies LIP traffic in Ollama logs when multiple consumers share a
# daemon (the warm-up loop, dev requests, etc.). httpx's default
# ``python-httpx/<v>`` is also fine but uniform LIP-prefixed agents
# simplify multi-instance debugging.
_USER_AGENT: Final[str] = "lip/0.1 (httpx)"

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
        # httpx.MockTransport without a live Ollama.
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": _USER_AGENT},
        )
        self._base_url = base_url

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient. Idempotent."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        """Enter async context manager; returns self for `async with` binding."""
        logger.info("ollama_client_connected", base_url=self._base_url)
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        """Exit async context manager; close underlying client without masking body errors.

        If the body of ``async with`` raised E1 and ``close()`` raises E2,
        Python normally replaces the visible exception with E2 (chaining
        E1 via ``__context__``). We log-and-suppress E2 so the body's E1
        remains the visible signal at the call site.
        """
        try:
            await self.close()
        except BaseException as close_exc:  # noqa: BLE001 - intentionally suppress to preserve body error
            logger.warning(
                "ollama_client_close_failed",
                exc_type=type(close_exc).__name__,
                exc_message=str(close_exc)[:200],
            )
        logger.info("ollama_client_closed", base_url=self._base_url)

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

        logger.info("ollama_call_started", model_id=model_tag, message_count=len(messages))
        response = await self._request("POST", "/api/chat", json=body)
        response.raise_for_status()
        result = build_chat_result(response.json())
        logger.info(
            "ollama_call_completed",
            model_id=model_tag,
            status_code=response.status_code,
            finish_reason=result.finish_reason,
        )
        return result
