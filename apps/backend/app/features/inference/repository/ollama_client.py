"""Lifecycle-managed httpx.AsyncClient wrapper for talking to Ollama."""

import json as _json
import time
from collections.abc import Mapping
from importlib import metadata as _metadata
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final, Literal, Self, cast

import httpx
import structlog

from app.core.logging import EXC_MESSAGE_PREVIEW_MAX_CHARS
from app.features.inference.model.ollama_translation import (
    build_chat_result,
    translate_message,
    translate_params,
)

logger = structlog.get_logger(__name__)


if TYPE_CHECKING:
    from app.features.inference.model.message import Message
    from app.features.inference.model.model_params import ModelParams
    from app.features.inference.model.ollama_chat_result import OllamaChatResult

# 600s read backstop bounds a hung Ollama daemon when no per-request budget
# is wrapped around the call. Generous enough not to interrupt long thinking-mode
# inference; finite enough that a wedged daemon eventually releases the slot.
# ``pool=5.0`` bounds pool-slot acquisition; with the F001 semaphore set to 1
# in-flight, pool starvation should be unreachable today, but a finite ceiling
# converts a future regression (a sibling adapter call holding a slot) into a
# loud ``httpx.PoolTimeout`` rather than a silent hang.
DEFAULT_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(
    connect=5.0,
    read=600.0,
    write=None,
    pool=5.0,
)

# Single Ollama target serialized through one in-flight slot — pool sized to
# match the F001 semaphore (max_in_flight=1) so a regression that leaks the
# semaphore surfaces as a loud ``httpx.PoolTimeout`` rather than letting two
# concurrent dials slip through silently. Keepalive_expiry pins the idle hold
# time so log churn and any future idle-shutdown coordinator have a known knob.
# See DEFAULT_TIMEOUT.pool=5.0 for the matching pool-acquisition deadline.
DEFAULT_LIMITS: Final[httpx.Limits] = httpx.Limits(
    max_connections=1,
    max_keepalive_connections=1,
    keepalive_expiry=30.0,
)

# HTTP verbs the adapter actually uses against Ollama. Narrowed at the
# `_request` boundary so a typo (`"PSOT"`) is a static error, not a 405
# at runtime. Add a verb here only when a new adapter method needs it.
type HttpMethod = Literal["GET", "POST"]


def _decode_ollama_json(response: httpx.Response) -> dict[str, Any]:
    """Decode Ollama JSON, normalizing non-JSON bodies to ValueError.

    Builds one malformed-response category for the failure-mapping layer to
    translate, instead of leaking httpx's untyped JSONDecodeError out of the
    seam. ``ValueError`` (not ``KeyError``) is the canonical Python exception
    for "right shape, wrong value" — Python's data model reserves ``KeyError``
    for mapping/dict-access misses, and using it as a generic malformed-frame
    sentinel collides with real ``KeyError``s the failure-mapping layer would
    otherwise have to disambiguate.

    No ``ollama_response_malformed`` log line is emitted here: the downstream
    ``chat`` except path's ``ollama_call_failed`` line carries
    ``exc_message=`` with the same diagnostic information, so a per-branch
    log here would double-count the same failure.
    """
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        error_message = f"Ollama returned non-JSON content-type {content_type!r}."
        raise ValueError(error_message)
    try:
        payload: Any = response.json()
    except _json.JSONDecodeError as decode_exc:
        error_message = "Ollama returned non-JSON body under stream=False."
        raise ValueError(error_message) from decode_exc
    if not isinstance(payload, dict):
        error_message = f"Ollama returned non-object JSON body of type {type(payload).__name__}."
        # ``ValueError`` (not the TRY004-preferred ``TypeError``) so every
        # malformed-Ollama-frame case routes through one exception type the
        # failure-mapping layer (LIP-E003-F003) catches uniformly. Mixing
        # TypeError with ValueError here would force the mapping to handle
        # two exception families for one logical failure category.
        raise ValueError(error_message)  # noqa: TRY004 — unified malformed-frame signal
    return cast("dict[str, Any]", payload)


class OllamaClient:
    """Lifecycle-managed httpx.AsyncClient for talking to Ollama.

    Constructed at app lifespan startup; the underlying ``httpx.AsyncClient``
    is acquired in ``__aenter__`` and closed at ``__aexit__`` so the
    AsyncExitStack owns the connection lifecycle from acquisition. The
    private ``_request`` is the lower-level seam other adapter methods build
    on top of from *within* this class. External callers go through ``chat``
    (or a future typed sibling) — ``_request`` and ``_client`` are
    single-underscore by convention. Tests are exempt from ``SLF001`` via
    the per-file-ignores in pyproject.toml; non-test code accessing them is
    a lint failure.
    """

    def __init__(
        self,
        base_url: str,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Eager parse: an unparseable ``base_url`` should fail loudly here,
        # not at the first request with a confusing httpx.InvalidURL. The
        # parsed form also feeds the per-call loggable URL so a future
        # AnyHttpUrl with embedded credentials cannot leak via per-request
        # log lines (the host:port form is what operators care about anyway).
        parsed = httpx.URL(base_url)
        host_only = parsed.host
        port = parsed.port
        self._loggable_base_url = (
            f"{parsed.scheme}://{host_only}:{port}" if port else f"{parsed.scheme}://{host_only}"
        )

        # Defer ``httpx.AsyncClient`` construction to ``__aenter__`` so the
        self._base_url = base_url
        # User-Agent is computed per-instance so the ``PackageNotFoundError``
        # fallback is reachable from unit tests via monkeypatch on the
        # instance method; module-scope evaluation made the warning branch
        # untestable.
        self._user_agent = self._build_user_agent()
        client_kwargs: dict[str, Any] = {
            "base_url": base_url,
            "timeout": timeout,
            "limits": DEFAULT_LIMITS,
            "headers": {"User-Agent": self._user_agent},
            # Defense-in-depth vs SSRF: a redirected target bypasses
            # ``Settings._check_safety_invariants``'s loopback/private-host
            # clamp on ``ollama_host``. Flipping this to ``True`` would
            # weaken that defense, so the choice is annotated rather than
            # implicit.
            "follow_redirects": False,
            # Defense-in-depth vs proxy/credential leakage: httpx defaults to
            # ``trust_env=True`` which honors HTTPS_PROXY / NO_PROXY / ~/.netrc
            # from the operator's shell. For a loopback/LAN-only target, an
            # exported corp proxy would silently route prompt content through
            # an unintended hop — defeating the SSRF clamp on ollama_host.
            # Flip to False so the proxy decision is an explicit Settings
            # field if it ever becomes one.
            "trust_env": False,
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        self._client = httpx.AsyncClient(**client_kwargs)
        # Debug-level construction trace so operators can verify wire-config
        # (TLS, redirects, pool, timeout) under -v without adding info noise.
        logger.debug(
            "ollama_client_constructed",
            base_url=self._loggable_base_url,
            follow_redirects=False,
            trust_env=False,
            max_connections=DEFAULT_LIMITS.max_connections,
            read_timeout_s=DEFAULT_TIMEOUT.read,
        )

    def _build_user_agent(self) -> str:
        """Return an RFC 7231 product-token User-Agent string for Ollama logs.

        Reads the LIP package version from importlib.metadata so the UA
        stays aligned with ``pyproject.toml`` automatically; falls back to
        ``unknown`` if the package metadata is unavailable (editable install
        in a context where importlib.metadata can't see the dist-info).
        Emits a ``ollama_user_agent_version_missing`` warning before the
        fallback so the silent-substitution case is visible to operators.
        """
        try:
            lip_version = _metadata.version("lip-backend")
        except _metadata.PackageNotFoundError:
            logger.warning("ollama_user_agent_version_missing")
            lip_version = "unknown"
        return f"lip-backend/{lip_version} httpx/{httpx.__version__}"

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient. Idempotent."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        """Enter async context manager."""
        logger.info("ollama_client_lifecycle_entered", base_url=self._loggable_base_url)
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        """Exit async context manager; close underlying client.

        Body-error preservation: when the body raised E1 (``_exc is not
        None``) and ``aclose()`` raises E2, we log-and-suppress E2 so the
        body's E1 remains visible. When the body did NOT raise
        (``_exc is None``) but ``aclose()`` does, we let the close error
        propagate — there is no body error to mask, and a silently-failed
        close is itself a bug worth surfacing.

        The ``Exception`` narrow lets ``CancelledError`` /
        ``KeyboardInterrupt`` / ``SystemExit`` propagate either way (their
        suppression would break structured concurrency).

        ``ollama_client_closed`` lands on the ``else:`` branch so the success
        and failure events are mutually exclusive — operators reading
        ``ollama_client_close_failed`` are not also chased by a misleading
        ``ollama_client_closed`` line on the same shutdown.
        """
        try:
            await self.close()
        except Exception as close_exc:
            # ``logger.exception`` auto-resolves the active exception via
            # ``sys.exc_info()``; no need to thread ``exc_info=close_exc``.
            logger.exception(
                "ollama_client_close_failed",
                exc_type=type(close_exc).__name__,
            )
            if _exc is None:
                # No body error to preserve — propagate so a silently-failed
                # close surfaces as a real shutdown failure rather than
                # a swallowed warning.
                raise
        else:
            logger.info("ollama_client_closed", base_url=self._loggable_base_url)

    async def _request(
        self,
        method: HttpMethod,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Low-level passthrough to httpx — used by sibling adapter features."""
        return await self._client.request(
            method,
            path,
            json=json,
            params=params,
            headers=headers,
        )

    async def chat(
        self,
        *,
        model_tag: str,
        messages: "list[Message]",
        params: "ModelParams",
    ) -> "OllamaChatResult":
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

        # Hoisted before ``try`` so both the ``Exception`` and
        # ``BaseException`` arms log the same field set. The ``Exception``
        # arm overrides ``status_code`` only when the exception is
        # ``httpx.HTTPStatusError``; the ``BaseException`` arm leaves it
        # at ``None``.
        ollama_status_code: int | None = None
        # ``option_keys`` (sorted, keys-only) lets operators see the request
        # shape on the failure log without leaking sampling-param values or
        # any consumer prompt content. base_url is intentionally not logged
        # per-call: it's constant for the client's lifetime and present on
        # the lifecycle-entered/closed lines.
        option_keys = sorted(options) if options else []

        # ``debug`` (not ``info``): the call-completed line already carries
        # duration_ms and outcome — the started line is correlation glue
        # that operators only need at debug log level. Keeping it info would
        # double the call-related log volume in steady state. Note that the
        # ``except Exception`` below narrows to Exception (NOT BaseException)
        # so a ``CancelledError`` from a disconnected consumer propagates
        # upstream and the in-flight semaphore slot (LIP-E001-F002) releases
        # promptly. We DO emit a separate cancellation log so the cancelled
        # call is visible at info level without bumping the start-line
        # verbosity globally.
        logger.debug(
            "ollama_call_started",
            model_id=model_tag,
            message_count=len(messages),
        )
        start = time.perf_counter()
        try:
            response = await self._request("POST", "/api/chat", json=body)
            response.raise_for_status()
            payload = _decode_ollama_json(response)
            result = build_chat_result(payload)
        except Exception as call_exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            # Use isinstance-narrow rather than getattr-chain so pyright sees
            # an explicit ``int | None`` for status_code instead of Any flowing
            # into the structured log line. httpx.HTTPStatusError is the only
            # exception type that carries a typed response.status_code.
            if isinstance(call_exc, httpx.HTTPStatusError):
                ollama_status_code = call_exc.response.status_code
            # ``logger.exception`` (not ``logger.warning``): we ARE inside an
            # except block, so structlog auto-attaches the traceback via
            # ``sys.exc_info`` and the level marks the event as the original
            # raise-site capture for grep-by-level dashboards. ``exc_message``
            # is httpx-side infrastructure data (or a malformed-frame
            # ``ValueError``); never user prompt content, so it is safe to log.
            logger.exception(
                "ollama_call_failed",
                model_id=model_tag,
                exc_type=type(call_exc).__name__,
                exc_message=str(call_exc)[:EXC_MESSAGE_PREVIEW_MAX_CHARS],
                ollama_status_code=ollama_status_code,
                duration_ms=duration_ms,
                option_keys=option_keys,
                message_count=len(messages),
            )
            raise
        except BaseException as cancel_exc:
            # Cancellation (consumer disconnect, lifespan shutdown) bypasses
            # the Exception arm above, which is correct for propagation, but
            # would otherwise leave NO log evidence the call started reaching
            # Ollama. Emit a single ``ollama_call_cancelled`` line so the
            # operator can correlate via request_id, then re-raise so the
            # cancellation continues to propagate (BaseException narrowing
            # protects structured concurrency — never suppress).
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.warning(
                "ollama_call_cancelled",
                model_id=model_tag,
                exc_type=type(cancel_exc).__name__,
                duration_ms=duration_ms,
                ollama_status_code=ollama_status_code,
                option_keys=option_keys,
                message_count=len(messages),
            )
            raise
        duration_ms = int((time.perf_counter() - start) * 1000)
        # ``ollama_status_code`` intentionally omitted on success:
        # ``raise_for_status`` has already filtered to 2xx and Ollama
        # /api/chat only returns 200 on success today, so the field would be
        # a constant. The failure path keeps it because it's the load-bearing
        # diagnostic there.
        logger.info(
            "ollama_call_completed",
            model_id=model_tag,
            duration_ms=duration_ms,
            finish_reason=result.finish_reason,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            message_count=len(messages),
            option_keys=option_keys,
        )
        return result
