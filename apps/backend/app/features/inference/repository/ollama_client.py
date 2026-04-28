"""Lifecycle-managed httpx.AsyncClient wrapper for talking to Ollama."""

from __future__ import annotations

import json as _json
import time
from typing import TYPE_CHECKING, Any, Final, Literal, Self, cast

import httpx
import structlog

from app.features.inference.repository.ollama_translation import (
    build_chat_result,
    translate_message,
    translate_params,
)

logger = structlog.get_logger(__name__)

_USER_AGENT: Final[str] = "lip/0.1 (httpx)"

if TYPE_CHECKING:
    from types import TracebackType

    from app.features.inference.model.message import Message
    from app.features.inference.model.model_params import ModelParams
    from app.features.inference.model.ollama_chat_result import OllamaChatResult

# 600s read backstop bounds a hung Ollama daemon when no per-request budget
# is wrapped around the call. Generous enough not to interrupt long thinking-mode
# inference; finite enough that a wedged daemon eventually releases the slot.
DEFAULT_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(
    connect=5.0,
    read=600.0,
    write=None,
    pool=None,
)

# Single Ollama target serialized through one in-flight slot — small pool sized
# to match. Keepalive_expiry pins the idle hold time so log churn and any future
# idle-shutdown coordinator have a known knob.
DEFAULT_LIMITS: Final[httpx.Limits] = httpx.Limits(
    max_connections=2,
    max_keepalive_connections=2,
    keepalive_expiry=30.0,
)

# HTTP verbs the adapter actually uses against Ollama. Narrowed at the
# `_request` boundary so a typo (`"PSOT"`) is a static error, not a 405
# at runtime. Add a verb here only when a new adapter method needs it.
type HttpMethod = Literal["GET", "POST"]


def _decode_ollama_json(response: httpx.Response) -> dict[str, Any]:
    """Decode Ollama JSON, normalizing non-JSON bodies to KeyError.

    Builds one malformed-response category for the failure-mapping layer to
    translate, instead of leaking httpx's untyped JSONDecodeError out of the
    seam.
    """
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        error_message = f"Ollama returned non-JSON content-type {content_type!r}."
        raise KeyError(error_message)
    try:
        payload: Any = response.json()
    except _json.JSONDecodeError as decode_exc:
        error_message = "Ollama returned non-JSON body under stream=False."
        raise KeyError(error_message) from decode_exc
    if not isinstance(payload, dict):
        error_message = f"Ollama returned non-object JSON body of type {type(payload).__name__}."
        raise KeyError(error_message)
    return cast("dict[str, Any]", payload)


class OllamaClient:
    """Lifecycle-managed httpx.AsyncClient for talking to Ollama.

    Constructed at app lifespan startup; closed at lifespan shutdown. The
    private ``_request`` is the lower-level seam other adapter methods
    build on top of from *within* this class. External callers go through
    ``chat`` (or a future typed sibling) — ``_client`` and ``_request``
    are single-underscore by convention and ``SLF001``-enforced for
    non-test code.
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
        client_kwargs: dict[str, Any] = {
            "base_url": base_url,
            "timeout": timeout,
            "limits": DEFAULT_LIMITS,
            "follow_redirects": False,
            "headers": {"User-Agent": _USER_AGENT},
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        self._client = httpx.AsyncClient(**client_kwargs)
        self._base_url = base_url

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient. Idempotent."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        """Enter async context manager; returns self for `async with` binding."""
        # No socket has opened yet — httpx pools lazily on first request — so the
        # event name reflects "lifespan-entered", not "TCP-handshake-complete".
        logger.info("ollama_client_lifecycle_entered", base_url=self._base_url)
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        """Exit async context manager; close underlying client without masking body errors.

        If the body raised E1 and close() raises E2, Python would normally surface
        E2; we log-and-suppress E2 so the body's E1 remains visible. The except
        narrows to ``Exception`` so ``CancelledError`` / ``KeyboardInterrupt`` /
        ``SystemExit`` propagate (their suppression would break structured
        concurrency).
        """
        try:
            await self.close()
        except Exception as close_exc:  # noqa: BLE001 — intentionally suppress non-cancellation close errors to preserve body error
            logger.warning(
                "ollama_client_close_failed",
                exc_type=type(close_exc).__name__,
                exc_message=str(close_exc)[:200],
                exc_info=close_exc,
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

        ``model_tag`` is the registry-resolved backend tag. ``params`` is
        already merged over registry defaults by the caller. Failure
        mapping (httpx exceptions -> typed DomainError) wraps this method.
        """
        # Field order intentionally mirrors the Ollama /api/chat spec
        # example body (model, messages, options, stream) so wire dumps
        # are reviewable side-by-side with upstream API docs. ``think``
        # rides inside ``options`` per LIP-E003-F002 [RESOLVED].
        body: dict[str, Any] = {
            "model": model_tag,
            "messages": [translate_message(m) for m in messages],
        }
        options = translate_params(params)
        if options:
            body["options"] = options
        body["stream"] = False

        logger.info("ollama_call_started", model_id=model_tag, message_count=len(messages))
        start = time.perf_counter()
        try:
            response = await self._request("POST", "/api/chat", json=body)
            response.raise_for_status()
            payload = _decode_ollama_json(response)
            result = build_chat_result(payload)
        except Exception as call_exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            status_code = getattr(getattr(call_exc, "response", None), "status_code", None)
            # exc_info preserves the traceback so operator triage doesn't
            # collapse to "exc_type=ReadTimeout" on a wedged Ollama — the
            # original raise site is the most actionable signal.
            logger.warning(
                "ollama_call_failed",
                model_id=model_tag,
                exc_type=type(call_exc).__name__,
                status_code=status_code,
                duration_ms=duration_ms,
                exc_info=call_exc,
            )
            raise
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "ollama_call_completed",
            model_id=model_tag,
            status_code=response.status_code,
            duration_ms=duration_ms,
            finish_reason=result.finish_reason,
        )
        return result
