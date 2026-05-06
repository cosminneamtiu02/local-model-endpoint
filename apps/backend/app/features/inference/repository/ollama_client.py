"""Lifecycle-managed httpx.AsyncClient wrapper for talking to Ollama."""

import asyncio
import json as _json
import time
from importlib import metadata as _metadata
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final, Literal, Self, cast

import httpx
import structlog
from pydantic import ValidationError as PydanticValidationError

from app.core.logging import EXC_MESSAGE_PREVIEW_MAX_CHARS, ascii_safe, elapsed_ms
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
# ``pool=5.0`` bounds pool-slot acquisition; with the LIP-E004-F001
# semaphore set to 1 in-flight, pool starvation should be unreachable
# today, but a finite ceiling converts a future regression (a sibling
# adapter call holding a slot) into a loud ``httpx.PoolTimeout`` rather
# than a silent hang.
DEFAULT_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(
    connect=5.0,
    read=600.0,
    write=None,
    pool=5.0,
)
# httpx.Timeout / httpx.Limits are plain Python objects without slots or
# property guards in 0.28.1 — direct attribute writes succeed. Module-
# level sharing across OllamaClient instances is nonetheless safe because
# no code path in LIP mutates these objects after construction; AsyncClient
# copies the relevant fields onto its own state at __init__-time. The
# invariant we rely on is "no caller mutates," not "the type is immutable."

# Single Ollama target serialized through one in-flight slot — pool sized to
# match the LIP-E004-F001 semaphore (max_in_flight=1) so a regression that
# leaks the semaphore surfaces as a loud ``httpx.PoolTimeout`` rather than
# letting two concurrent dials slip through silently. Keepalive_expiry pins
# the idle hold time so log churn and any future idle-shutdown coordinator
# have a known knob. See DEFAULT_TIMEOUT.pool=5.0 for the matching pool-
# acquisition deadline.
DEFAULT_LIMITS: Final[httpx.Limits] = httpx.Limits(
    max_connections=1,
    max_keepalive_connections=1,
    keepalive_expiry=30.0,
)

# HTTP verbs the adapter actually uses against Ollama. Narrowed at the
# `_request` boundary so a typo (`"PSOT"`) is a static error, not a 405
# at runtime. Add a verb here only when a new adapter method needs it.
type HttpMethod = Literal["GET", "POST"]

# Wire path for the Ollama chat endpoint. Centralized so a future Ollama
# version bump (or reverse-proxy rewrite to ``/v1/api/chat``) is a one-
# line edit and the wire-vs-log fields in ``chat()`` cannot drift apart.
# Operator dashboards keying on ``select(.endpoint == "/api/chat")`` pin
# off this constant transitively.
_CHAT_ENDPOINT: Final[str] = "/api/chat"


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

    Caller contract: ``response`` must come from a non-streaming httpx call
    (``client.request(...)``, NOT ``client.stream(...)``). httpx 0.28
    auto-reads the body during ``client.request`` so ``response.headers`` /
    ``response.json()`` work without an explicit ``aread()``. A future
    sibling method that switches to streaming (e.g. for an Ollama ``pull``
    progress feed) MUST ``await response.aread()`` before reusing this
    helper, or the non-JSON / decode-error arms below will leak a
    streaming connection slot until GC.
    """
    # RFC 7231 §3.1.1.1: media-type names are case-insensitive.
    # Strip OWS (RFC 7231 §3.2.4 allows surrounding whitespace on field
    # values) and lowercase before compare so a future reverse proxy that
    # normalizes to ``  Application/JSON `` does not silently bypass this
    # guard and re-bucket a real Ollama response as malformed-frame.
    content_type = response.headers.get("content-type", "").strip().lower()
    # Tighter than ``startswith("application/json")``: that prefix would
    # admit ``application/json-seq`` (streaming-JSON sequences),
    # ``application/jsonp`` (browser bridge formats), and any future
    # ``application/json*`` family member with surprise framing.
    # Accept only the bare media-type or media-type-with-parameters form
    # (``application/json`` exact, or ``application/json;charset=utf-8``).
    if content_type != "application/json" and not content_type.startswith("application/json;"):
        msg = f"Ollama returned non-JSON content-type {content_type!r}."
        raise ValueError(msg)
    try:
        payload: Any = response.json()
    except _json.JSONDecodeError as decode_exc:
        msg = "Ollama returned non-JSON body under stream=False."
        raise ValueError(msg) from decode_exc
    if not isinstance(payload, dict):
        msg = f"Ollama returned non-object JSON body of type {type(payload).__name__}."
        # ``ValueError`` (not the TRY004-preferred ``TypeError``) so every
        # malformed-Ollama-frame case routes through one exception type the
        # failure-mapping layer (LIP-E003-F003) catches uniformly. Mixing
        # TypeError with ValueError here would force the mapping to handle
        # two exception families for one logical failure category.
        raise ValueError(msg)  # noqa: TRY004 — unified malformed-frame signal
    return cast("dict[str, Any]", payload)


class OllamaClient:
    """Lifecycle-managed httpx.AsyncClient for talking to Ollama.

    Constructed at app lifespan startup. The underlying
    ``httpx.AsyncClient`` is built in ``__init__`` (httpx's pool is
    lazily allocated on first request, so this is cheap) and closed at
    ``__aexit__`` (or via explicit ``close()``); ``__aenter__`` is the
    lifecycle log marker, not the acquisition site. The AsyncExitStack
    in ``app.api.lifespan_resources.lifespan_resources`` owns the close
    side via ``async with`` so the connection lifecycle is bounded by
    the FastAPI app's lifespan window. The private ``_request`` is the
    lower-level seam other adapter methods build on top of from *within*
    this class. External callers go through ``chat`` (or a future typed
    sibling) — ``_request`` and ``_client`` are single-underscore by
    convention. Tests are exempt from ``SLF001`` via the per-file-ignores
    in pyproject.toml; non-test code accessing them is a lint failure.
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
        # parsed form also feeds the per-call loggable URL via httpx's
        # ``netloc`` accessor — which excludes ``userinfo`` by design (httpx
        # parses credentials into the separate ``userinfo`` byte attribute),
        # giving defense-in-depth against credential leakage even though
        # ``Settings._check_safety_invariants`` already rejects userinfo in
        # ``ollama_host``. Default-port elision is httpx's choice (verified:
        # ``URL("http://x:80").netloc`` returns ``b"x"``).
        parsed = httpx.URL(base_url)
        # ``parsed.path`` (str in httpx 0.28) is included as defense-in-
        # depth; ``Settings._check_safety_invariants`` already rejects
        # path segments in ``LIP_OLLAMA_HOST`` (only "" and "/" pass), so
        # this branch is unreachable today — but keeping it preserves
        # full-target visibility if a future ADR relaxes the path screen
        # (e.g. for an Ollama gateway that requires ``/api/v1`` prefix).
        # Normalize a missing path to "/" so the loggable URL shape is
        # invariant under ``AnyHttpUrl``'s trailing-slash normalization
        # (production passes ``str(AnyHttpUrl(...))`` which adds the
        # slash; test fixtures often pass the bare ``"http://host:port"``
        # form). Operator dashboards keying on
        # ``select(.base_url == "http://localhost:11434/")`` then match
        # both shapes.
        path_segment = parsed.path or "/"
        self._loggable_base_url = (
            f"{parsed.scheme}://{parsed.netloc.decode('ascii', errors='replace')}{path_segment}"
        )
        # Lifetime measurement seam — set in ``__aenter__`` and read in
        # ``__aexit__`` to compute ``duration_ms`` on the close event so
        # the lifecycle pair has parity (entry surfaces config, close
        # surfaces lifetime).
        self._lifecycle_entered_at: float | None = None

        # User-Agent is computed per-instance so the ``PackageNotFoundError``
        # fallback is reachable from unit tests via monkeypatch on the
        # instance method. Local (not ``self._user_agent``) because the
        # value is consumed exactly once below and the instance attribute
        # would widen the public-via-introspection surface unnecessarily.
        user_agent = self._build_user_agent()
        # Defense-in-depth vs userinfo leakage: ``Settings._check_safety_
        # invariants`` already rejects userinfo on ``LIP_OLLAMA_HOST``, but
        # the public ``OllamaClient`` constructor accepts any ``base_url``
        # str (test fixtures, future sibling callers). Strip userinfo
        # before threading into ``httpx.AsyncClient`` so a credential-
        # bearing URL cannot reach the wire even if the Settings clamp is
        # ever bypassed. ``copy_with(userinfo=b"")`` is an unconditional
        # no-op when userinfo is already empty, so the strip is cheap.
        safe_base_url = str(parsed.copy_with(userinfo=b""))
        # Pass ``transport=transport`` unconditionally: ``httpx.AsyncClient``
        # treats ``transport=None`` as "use the default transport," so the
        # branch-on-None pattern was extra typing surface for no behavior
        # difference. Direct kwargs keeps the precise httpx types instead of
        # collapsing to ``dict[str, Any]``.
        self._client = httpx.AsyncClient(
            base_url=safe_base_url,
            timeout=timeout,
            limits=DEFAULT_LIMITS,
            # Explicit ``Accept`` header makes the symmetry with the
            # _decode_ollama_json content-type guard self-documenting: LIP
            # only consumes JSON, and a future Ollama version supporting
            # content negotiation (or a misconfigured reverse proxy) gets a
            # clear signal rather than landing as an HTML error page.
            # ``Content-Type`` is NOT set here at the client level: httpx
            # 0.28 auto-stamps ``Content-Type: application/json`` per-
            # request when the caller threads ``json=...`` (every
            # ``_request`` POST does). A future sibling adapter that uses
            # ``content=...`` or ``data=...`` instead would need to set
            # the header explicitly at that call site — declaring it
            # globally here would mis-tag those bodies.
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
            },
            # Defense-in-depth vs SSRF: a redirected target bypasses
            # ``Settings._check_safety_invariants``'s loopback/private-host
            # clamp on ``ollama_host``. Flipping this to ``True`` would
            # weaken that defense, so the choice is annotated rather than
            # implicit.
            follow_redirects=False,
            # Defense-in-depth vs proxy/credential leakage: httpx defaults to
            # ``trust_env=True`` which honors HTTPS_PROXY / NO_PROXY / ~/.netrc
            # from the operator's shell. For a loopback/LAN-only target, an
            # exported corp proxy would silently route prompt content through
            # an unintended hop — defeating the SSRF clamp on ollama_host.
            # Flip to False so the proxy decision is an explicit Settings
            # field if it ever becomes one.
            trust_env=False,
            # Explicit ``verify=True`` (the httpx 0.28.1 default) so a
            # future httpx default flip (or a contributor copy-pasting
            # this constructor with ``verify=False`` for a self-signed
            # local cert) cannot silently weaken TLS for the
            # ``LIP_OLLAMA_HOST=https://...`` case. Kwarg parity with the
            # ``follow_redirects``/``trust_env`` defense-in-depth toggles.
            verify=True,
            transport=transport,
        )
        # No construction-time log: ``__aenter__`` (the actual lifecycle
        # entry, see ``ollama_client_lifecycle_entered`` below) is the
        # canonical lifecycle event AND it lands inside the
        # ``phase="lifespan"`` contextvar binding established by
        # ``lifespan_resources.lifespan_resources``. Logging from ``__init__``
        # would have to emit before that binding when the class is
        # instantiated outside an ``async with`` (as in tests), shipping
        # a wire-config line without ``phase`` context.
        #
        # Carve-out: ``_build_user_agent`` (called above as part of the
        # ``headers=`` kwarg) emits a single ``ollama_user_agent_version_
        # missing`` warning on the editable-install / dist-info-missing
        # branch. That warning is operator-actionable enough to ship
        # without ``phase`` context — losing the editable-install diagnostic
        # behind a deferred-to-``__aenter__`` move would obscure the
        # observability gap on a path that is rare but real. The "no
        # construction-time log" rule applies to wire-config telemetry; the
        # missing-version warning is a metadata anomaly, not telemetry.

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
            # ``phase="lifespan"`` for field-set parity with the rest of
            # the OllamaClient lifecycle events (entered/closed/close_failed)
            # so an operator's ``select(.phase == "lifespan")`` filter
            # finds the editable-install diagnostic uniformly even when
            # the client is constructed outside the lifespan_resources
            # contextvar binding (test fixtures using ``async with
            # OllamaClient(...)`` directly).
            logger.warning(
                "ollama_user_agent_version_missing",
                package_name="lip-backend",
                fallback_version="unknown",
                phase="lifespan",
            )
            lip_version = "unknown"
        return f"lip-backend/{lip_version} httpx/{httpx.__version__}"

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient. Idempotent.

        Idempotence is enforced here rather than relying on httpx's
        internal pool state — a future httpx version that raises on
        double-close would otherwise break the lifespan teardown's
        AsyncExitStack unwind silently.
        """
        if self._client.is_closed:
            return
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        """Enter async context manager."""
        # Surface the timeout/limits config at the lifecycle-entry seam so an
        # operator triaging a future ``PoolTimeout`` / read-timeout has the
        # client-build config recorded in logs without spelunking source.
        # One emit per process lifetime, so the cost is trivial and the
        # rationale comments at DEFAULT_TIMEOUT/DEFAULT_LIMITS get an
        # operator-readable echo that survives source refactors.
        # ``phase="lifespan"`` is also bound by ``lifespan_resources`` via
        # contextvars and rides in via ``merge_contextvars`` on the happy
        # path. Passing it explicitly here gives field-set parity for tests
        # / scripts that instantiate the client directly via ``async with
        # OllamaClient(...)`` outside the lifespan binding — the operator's
        # ``select(.phase == "lifespan")`` filter then catches every
        # lifecycle event uniformly. Track ``_lifecycle_entered_at`` so
        # ``__aexit__`` can compute ``duration_ms`` for the close event.
        self._lifecycle_entered_at = time.perf_counter()
        logger.info(
            "ollama_client_lifecycle_entered",
            base_url=self._loggable_base_url,
            phase="lifespan",
            timeout_connect=DEFAULT_TIMEOUT.connect,
            timeout_read=DEFAULT_TIMEOUT.read,
            timeout_pool=DEFAULT_TIMEOUT.pool,
            max_connections=DEFAULT_LIMITS.max_connections,
            max_keepalive_connections=DEFAULT_LIMITS.max_keepalive_connections,
            keepalive_expiry=DEFAULT_LIMITS.keepalive_expiry,
        )
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
        # ``duration_ms`` is the lifetime from ``__aenter__`` to close —
        # paired with ``_lifecycle_entered``'s timeout/limits config, the
        # operator's lifecycle dashboard now shows config-AND-lifetime per
        # client. ``None`` only when ``__aexit__`` is called outside the
        # ``async with`` happy path (a misuse the caller should fix); we
        # still emit the close events so the field-set asymmetry is the
        # diagnostic, not a hidden crash. The named warning below makes
        # the misuse a greppable event so an operator does not have to
        # infer it from a ``duration_ms=null`` field.
        if self._lifecycle_entered_at is None:
            logger.warning(
                "ollama_client_aexit_without_aenter",
                base_url=self._loggable_base_url,
                phase="lifespan",
            )
            duration_ms = None
        else:
            duration_ms = elapsed_ms(self._lifecycle_entered_at)
        try:
            await self.close()
        except Exception as close_exc:
            # ``logger.exception`` auto-resolves the active exception via
            # ``sys.exc_info()``; no need to thread ``exc_info=close_exc``.
            # ``base_url=`` + ``phase="lifespan"`` for field-set parity with
            # the ``_lifecycle_entered`` / ``_closed`` peers — operators
            # triaging a close failure can attribute by URL without
            # joining on a contextvar-bound ``phase`` alone (which is
            # absent when this client is constructed outside ``lifespan_
            # resources``, e.g. test fixtures using ``async with
            # OllamaClient(...)`` directly).
            logger.exception(
                "ollama_client_close_failed",
                base_url=self._loggable_base_url,
                phase="lifespan",
                exc_type=type(close_exc).__name__,
                duration_ms=duration_ms,
            )
            if _exc is None:
                # No body error to preserve — propagate so a silently-failed
                # close surfaces as a real shutdown failure rather than
                # a swallowed warning.
                raise
        else:
            logger.info(
                "ollama_client_closed",
                base_url=self._loggable_base_url,
                phase="lifespan",
                duration_ms=duration_ms,
            )

    async def _request(
        self,
        method: HttpMethod,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Low-level passthrough to httpx — used by sibling adapter features.

        Guards: ``path`` must be absolute (start with ``/``) so the future
        addition of ``base_url=".../v1"`` cannot silently RFC-3986-merge a
        relative ``"api/chat"`` into the wrong endpoint. ``self._client`` must
        not be closed — a leaked Depends-resolved reference arriving after
        lifespan teardown otherwise surfaces as httpx's untyped
        ``RuntimeError("Cannot send a request, as the client has been
        closed.")`` rather than a typed signal the failure-mapping layer
        (LIP-E003-F003) can translate.

        The signature is kept narrow on purpose: ``params=`` /
        ``headers=`` /  multipart kwargs are added back when the first
        sibling adapter method (``tags()`` / ``version()`` / ``embed()``)
        actually needs them, per ADR-011 ("build only what the current
        feature requires"). Today only ``chat`` calls in, and it threads
        only ``json=``.

        Path validation is intentionally minimal today (absolute-path-only)
        because ``path`` is a closed-alphabet literal at every current call
        site (the module-level ``_CHAT_ENDPOINT``). The first sibling
        adapter method that interpolates *consumer-controlled* data into
        ``path`` (e.g. ``f"/api/show/{model_tag}"``) MUST land a
        path-segment validation helper rejecting ``..`` / control chars /
        scheme-injection in the same PR — without it, a model-tag-shaped
        attacker input could escape the API root.
        """
        if not path.startswith("/"):
            msg = f"path must be absolute (start with /), got {path!r}"
            raise ValueError(msg)
        if self._client.is_closed:
            msg = "OllamaClient cannot be used after close()"
            raise RuntimeError(msg)
        return await self._client.request(method, path, json=json)

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
        # example body — ``(model, messages, options, stream)`` when
        # consumer-set sampling overrides exist, ``(model, messages,
        # stream)`` when ``options`` would be empty (omitted entirely so
        # the wire stays terse). Both shapes are spec-compatible; Ollama
        # treats a missing ``options`` field as "no overrides." ``think``
        # rides inside ``options`` (see ``translate_params``).
        body: dict[str, Any] = {
            "model": model_tag,
            "messages": [translate_message(m) for m in messages],
        }
        options = translate_params(params)
        if options:
            body["options"] = options
        body["stream"] = False

        # Hoisted before ``try`` so both the ``Exception`` and
        # ``CancelledError`` arms log the same field set. The
        # ``Exception`` arm overrides ``status_code`` only when the
        # exception is ``httpx.HTTPStatusError``; the ``CancelledError``
        # arm leaves it at ``None``. (The narrow second arm catches
        # ``asyncio.CancelledError`` rather than ``BaseException`` so
        # ``KeyboardInterrupt`` / ``SystemExit`` continue to propagate
        # without traversing this log path.)
        ollama_status_code: int | None = None
        # ``option_keys_sorted`` (keys-only, sorted) lets operators see the
        # request shape on the failure log without leaking sampling-param
        # values or any consumer prompt content. The wire body
        # ``body["options"]`` preserves Pydantic's field-declaration insertion
        # order; the log key is renamed to ``option_keys_sorted`` so a
        # reviewer cross-referencing log vs request capture is not surprised
        # by the order mismatch. base_url is intentionally not logged
        # per-call: it's constant for the client's lifetime and present on
        # the lifecycle-entered/closed lines.
        option_keys_sorted = sorted(options) if options else []

        # The ``except Exception`` below narrows to Exception (NOT
        # BaseException) so a ``CancelledError`` from a disconnected
        # consumer propagates upstream and the in-flight semaphore slot
        # (LIP-E001-F002) releases promptly. A separate cancellation log
        # below makes cancelled calls visible at INFO level alongside the
        # started/completed pair.
        #
        # Log key is ``model_name`` (not ``model``) so a jq filter
        # ``select(.model_name == "gemma4:e2b")`` matches both per-call lines
        # AND the ``model_name`` field on RegistryNotFoundError /
        # ModelCapabilityNotSupportedError problem+json bodies — single
        # source of truth for the model identifier across logs and wire
        # contract (errors.yaml param naming).
        # ``info`` (not ``debug``): on a wedged-daemon path (httpx connect/
        # read hangs forever, never raises and never completes), no
        # ``ollama_call_completed``/``_failed``/``_cancelled`` line ever
        # fires — operators querying ``select(.event == "ollama_call_*")``
        # see no event for the request. The 600s read timeout bounds the
        # gap, but bumping the start line to INFO closes the 10-minute
        # observability hole at the cost of one log line per call (low LAN
        # volume; the started/completed pair stays terse). ``endpoint=`` is
        # the per-call path so a future sibling ``tags()`` / ``show()``
        # method (LIP-E002-F001) can reuse the ``ollama_call_*`` event
        # taxonomy and operators can ``select(.endpoint == "/api/chat")``
        # to disambiguate.
        # Capture ``start`` BEFORE the started-event emit so the
        # ``duration_ms`` on the completed/failed/cancelled lines
        # encloses the started-event's structlog rendering cost too —
        # microscopic on the JSON renderer (<100us) but it keeps
        # ``duration_ms`` a true upper bound on Ollama work and aligns
        # with the natural reading "start_clock → started → work →
        # end_clock → completed".
        start = time.perf_counter()
        logger.info(
            "ollama_call_started",
            model_name=model_tag,
            endpoint=_CHAT_ENDPOINT,
            message_count=len(messages),
            option_keys_sorted=option_keys_sorted,
        )
        try:
            response = await self._request("POST", _CHAT_ENDPOINT, json=body)
            response.raise_for_status()
            payload = _decode_ollama_json(response)
            result = build_chat_result(payload, model_tag=model_tag)
        except Exception as call_exc:
            duration_ms = elapsed_ms(start)
            # Use isinstance-narrow rather than getattr-chain so pyright sees
            # an explicit ``int | None`` for status_code instead of Any flowing
            # into the structured log line. httpx.HTTPStatusError is the only
            # exception type that carries a typed response.status_code.
            if isinstance(call_exc, httpx.HTTPStatusError):
                ollama_status_code = call_exc.response.status_code
            # Closed-alphabet bucket so operator triage queries can group
            # failures without string-matching on ``exc_type``. Defaults to
            # ``"unknown"`` so a future exception family that escapes the
            # enumerated categories surfaces as a known-unknown rather than
            # silently mis-bucketing. ``httpx.RequestError`` (the parent of
            # ``TimeoutException``/``NetworkError``/``ProtocolError``/
            # ``ProxyError``/``DecodingError``/``TooManyRedirects``) is the
            # documented httpx idiom for "any non-2xx-status transport
            # failure"; using the parent here makes the bucket robust
            # against future httpx hierarchy growth without per-subtype
            # maintenance. ``HTTPStatusError`` is checked first because it
            # ALSO inherits from ``HTTPError`` but carries a typed status,
            # which we want as a separate bucket. ``NotImplementedError``
            # is a known consumer-input shape (URL-only ImageContent, etc.)
            # that the translation layer raises before any wire I/O — give
            # it a dedicated bucket so dashboards can distinguish a
            # consumer-input bug from a wedged process.
            if isinstance(call_exc, httpx.HTTPStatusError):
                failure_category = "http_status"
            elif isinstance(call_exc, httpx.RequestError):
                failure_category = "transport"
            elif isinstance(call_exc, httpx.InvalidURL):
                # ``InvalidURL`` inherits directly from ``Exception`` in
                # httpx 0.28.x — NOT from ``RequestError`` — so without
                # this dedicated arm a future control-char-bearing path
                # (e.g. a sibling adapter method that builds path strings
                # from operator data) would fall through to ``"unknown"``
                # and defeat the dashboarding intent of the bucket above.
                # Today only ``chat`` is wired and the only path is the
                # literal ``_CHAT_ENDPOINT``, so this arm is preventive.
                failure_category = "transport"
            elif isinstance(call_exc, NotImplementedError):
                failure_category = "unsupported_input"
            elif isinstance(call_exc, ValueError | PydanticValidationError):
                # Pydantic v2 ``ValidationError`` is NOT a ``ValueError``
                # subclass (it derives directly from ``Exception``), so
                # without the explicit arm a Pydantic-validated frame
                # rejected by ``OllamaChatResult(...)`` (oversize content,
                # token-count cap exceeded, etc.) would land in
                # ``"unknown"`` instead of ``"malformed_frame"`` —
                # defeating the documented "every malformed-Ollama-frame
                # case routes through one bucket" intent and breaking
                # operator dashboards that distinguish a wedged-daemon
                # signal from a protocol-drift regression.
                failure_category = "malformed_frame"
            else:
                failure_category = "unknown"
            # ``logger.exception`` (not ``logger.warning``): we ARE inside an
            # except block, so structlog auto-attaches the traceback via
            # ``sys.exc_info`` and the level marks the event as the original
            # raise-site capture for grep-by-level dashboards. ``exc_message``
            # is httpx-side infrastructure data (or a malformed-frame
            # ``ValueError``); never user prompt content. The ASCII-replace +
            # truncate sequence neutralizes any control chars an httpx error
            # may have reflected from a malformed Ollama body — symmetric
            # with ``RequestIdMiddleware``'s X-Request-ID header sanitation —
            # so a malicious upstream cannot inject log-line forgeries under
            # the dev ConsoleRenderer.
            # ``prompt_tokens=None`` / ``completion_tokens=None`` for
            # field-set parity with ``ollama_call_completed`` so a jq filter
            # ``select(.event | startswith("ollama_call_")) | .prompt_tokens``
            # finds the field on every event in the lifecycle (same parity
            # discipline as ``ollama_status_code: int | None``).
            logger.exception(
                "ollama_call_failed",
                model_name=model_tag,
                endpoint=_CHAT_ENDPOINT,
                exc_type=type(call_exc).__name__,
                exc_message=ascii_safe(str(call_exc), max_chars=EXC_MESSAGE_PREVIEW_MAX_CHARS),
                failure_category=failure_category,
                ollama_status_code=ollama_status_code,
                duration_ms=duration_ms,
                prompt_tokens=None,
                completion_tokens=None,
                option_keys_sorted=option_keys_sorted,
                message_count=len(messages),
            )
            raise
        except asyncio.CancelledError as cancel_exc:
            # Cancellation (consumer disconnect, lifespan shutdown) bypasses
            # the Exception arm above, which is correct for propagation, but
            # would otherwise leave NO log evidence the call started reaching
            # Ollama. Emit a single ``ollama_call_cancelled`` line so the
            # operator can correlate via request_id, then re-raise so the
            # cancellation continues to propagate. Narrowed to
            # ``asyncio.CancelledError`` only (not ``BaseException``):
            # ``KeyboardInterrupt`` / ``SystemExit`` mean the process is
            # dying and don't need a per-call log line; ``GeneratorExit`` is
            # raised only inside async generators (``aclose``) and
            # ``chat()`` returns a typed value rather than yielding, so the
            # arm has no path to fire.
            duration_ms = elapsed_ms(start)
            # ``info`` (not ``warning``): consumer-disconnect cancellation is
            # expected traffic on a multi-consumer LAN service; logging at
            # warning would inflate the warning-rate baseline operators
            # dashboard against real failures. Lifespan-shutdown cancellation
            # is rarer but still normal — both fire here at info, peer to
            # ``ollama_call_completed``.
            # ``prompt_tokens=None`` / ``completion_tokens=None`` for
            # field-set parity with ``ollama_call_completed`` /
            # ``ollama_call_failed`` so a single jq filter walks all four
            # lifecycle events without coalesce-joins.
            logger.info(
                "ollama_call_cancelled",
                model_name=model_tag,
                endpoint=_CHAT_ENDPOINT,
                exc_type=type(cancel_exc).__name__,
                duration_ms=duration_ms,
                ollama_status_code=ollama_status_code,
                prompt_tokens=None,
                completion_tokens=None,
                option_keys_sorted=option_keys_sorted,
                message_count=len(messages),
            )
            raise
        duration_ms = elapsed_ms(start)
        # ``ollama_status_code`` intentionally omitted on success:
        # ``raise_for_status`` has already filtered to 2xx and Ollama
        # /api/chat only returns 200 on success today, so the field would be
        # a constant. The failure path keeps it because it's the load-bearing
        # diagnostic there.
        logger.info(
            "ollama_call_completed",
            model_name=model_tag,
            endpoint=_CHAT_ENDPOINT,
            duration_ms=duration_ms,
            finish_reason=result.finish_reason,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            message_count=len(messages),
            option_keys_sorted=option_keys_sorted,
        )
        return result
