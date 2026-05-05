"""Structured logging configuration with structlog.

This module is the SOLE approved location in the codebase for
``logging.getLogger``. There are TWO carve-out call sites at the
bottom of ``configure_logging``: one binds the JSON handler to the
root logger, the other silences ``uvicorn.access`` (which would
otherwise duplicate the ``request_completed`` line emitted by
``RequestIdMiddleware``). The CLAUDE.md "never use
logging.getLogger" sacred rule covers application code; this
bridge to stdlib's logger registry is the documented exception.
All other code uses ``structlog.get_logger``.
"""

import logging
import sys
import time
from collections.abc import Callable
from typing import Final

import structlog

EXC_MESSAGE_PREVIEW_MAX_CHARS: Final[int] = 200
"""Cap for ``exc_message=`` log fields where ``str(exc)`` is serialized.

Prevents an unbounded exception ``__str__`` (e.g. an httpx error reflecting
a multi-MB upstream body) from inflating the log line. Centralized here so
ollama_client.py and any future call site reuse one constant rather than
hand-rolling 200/256/500 caps.
"""

_MS_PER_SECOND: Final[int] = 1000


def elapsed_ms(start: float, *, now: Callable[[], float] = time.perf_counter) -> int:
    """Return integer milliseconds elapsed since ``start`` per ``now()``.

    Centralizes the ``int((time.perf_counter() - start) * 1000)`` pattern
    duplicated across :class:`RequestIdMiddleware`, :class:`OllamaClient`,
    and the lifespan ``app_shutdown`` line. Pass ``now=time.monotonic``
    for uptime measurements (immune to NTP jumps); the default
    ``time.perf_counter`` is the right choice for request-latency timing.
    """
    return int((now() - start) * _MS_PER_SECOND)


def ascii_safe(value: str | bytes, *, max_chars: int = EXC_MESSAGE_PREVIEW_MAX_CHARS) -> str:
    """Return ``value`` ASCII-replaced and truncated to ``max_chars``.

    Centralizes the "ASCII-clean a possibly-control-char-bearing
    user-supplied string before logging it" idiom that otherwise repeats
    across :class:`RequestIdMiddleware`, :class:`OllamaClient`, and the
    validation-error and HTTP-exception handlers. Keeping a single helper
    means a future regression (forgetting to truncate, dropping the
    encode step) cannot land in only one of the four call sites — and
    a future ops dashboard rendering log values into HTML is defended by
    one place, not four.

    Accepts ``bytes`` directly (avoids a separate encode step at byte-input
    sites) and ``str`` (pre-existing string with possible control chars).
    Non-ASCII bytes / chars are replaced with ``?``; control bytes (0x00-
    0x1F + 0x7F) are also replaced because terminals and HTML renderers
    treat them as special.
    """
    text = value.decode("ascii", errors="replace") if isinstance(value, bytes) else value
    return text.encode("ascii", errors="replace").decode("ascii")[:max_chars]


_REDACTION_BLOCKLIST: Final[frozenset[str]] = frozenset(
    {
        "messages",
        "content",
        "prompt",
        "tool_calls",
        "audios",
        "images",
        # Each entry below is a wire-shape concept present in the Ollama
        # /api/chat request or response. The CLAUDE.md ban (never log message
        # content / prompt text / model output / tool-call arguments) is the
        # primary contract; the entries here turn the backstop from "catches
        # the obvious names" into "catches the obvious AND the close-by-name
        # regression surface." Add new entries when a sibling adapter method
        # introduces a new prompt-bearing key shape.
        "arguments",
        "output",
        "output_text",
        "completion",
        "assistant_message",
        "model_output",
        # Tool-call / function-call surface naming variants. ``tool_calls``
        # above is Ollama's request-side key; ``tools`` is the request-side
        # tool-list (defining the available tools, which can include
        # prompt-shaped descriptions). ``tool_arguments`` / ``function_call``
        # / ``function_arguments`` cover the OpenAI-compatible legacy and
        # Anthropic-SDK naming variants — a future adapter shipping any of
        # these without going through the redaction-aware logger would defeat
        # the CLAUDE.md "never log tool-call arguments" rule via this seam.
        # ``tool_response`` / ``tool_result`` / ``tool_output`` cover the
        # response-side variants for round-tripped tool output, which can
        # echo consumer prompt content reflected by the tool — the
        # CLAUDE.md ban on "model output" logging extends to these.
        "tools",
        "tool_arguments",
        "function_call",
        "function_arguments",
        "tool_response",
        "tool_result",
        "tool_output",
        # Generic body / payload names a future debug-investigation diff
        # might use (``logger.info("oops", body=request_json)``). Operator
        # discipline catches it at code review; this is the
        # infrastructure-level backstop.
        "body",
        "payload",
        "request_body",
        "chat_request",
        "chat_response",
        # Close-by-name surface a future contributor might naturally use
        # without reaching for ``messages`` / ``content``. The CLAUDE.md
        # ban applies to "prompt text / model output / tool-call
        # arguments" regardless of the kwarg key the caller picks; these
        # variants extend the backstop to the regression-likely names.
        "input",
        "prompt_text",
        "system_prompt",
        "instruction",
        "text",
        "query",
    },
)
"""Event-dict keys whose values are unconditionally redacted.

Defense-in-depth backstop for the CLAUDE.md ban on logging consumer prompt
content. Caller discipline at every emit site is the primary contract; this
processor catches the regression where a future contributor adds
``messages=request.messages`` to a logger call. The processor only inspects
TOP-LEVEL keys — nested structures (e.g. ``logger.info("x", request=body)``
where ``body["messages"]`` lives one level down) are NOT scanned. Caller
discipline remains the primary contract; recursion would pay a per-call
cost on every log line for a regression that has never appeared.

Invariant: entries here MUST NOT collide with canonical-processor output
keys (``level``, ``logger``, ``timestamp``, ``event``, ``exception``).
``add_log_level``, ``add_logger_name``, and ``TimeStamper`` run AFTER
``_redact_sensitive_keys`` in the processor chain (see
``configure_logging`` below) and would clobber the ``<redacted>``
sentinel on those keys silently. Today no entries collide. Routing /
correlation keys (``path``, ``instance``, ``request_id``, ``method``,
``env_vars``) are also intentionally NOT redacted — they are pre-
sanitized at the bind site via ``ascii_safe`` and are load-bearing
operator telemetry; the ``audit_lip_env_typos`` warning specifically
needs ``env_vars`` names visible (CLAUDE.md ADR-014 carve-out).
"""


def _redact_sensitive_keys(
    _logger: structlog.typing.WrappedLogger,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    """Defense-in-depth backstop for CLAUDE.md prompt-content log ban.

    Replaces values for known-sensitive TOP-LEVEL keys with the
    ``"<redacted>"`` sentinel regardless of caller discipline. The
    CLAUDE.md ban is the primary contract; this processor is the
    infrastructure-level catch. Nested values are intentionally NOT
    scanned — see ``_REDACTION_BLOCKLIST`` docstring for the rationale.
    """
    # ``event_dict.keys() & _REDACTION_BLOCKLIST`` materializes a fresh
    # ``frozenset`` (not a live ``dict_keys`` view), so mutating
    # ``event_dict`` during iteration is safe under CPython. Do NOT
    # replace with ``for key in event_dict if key in _REDACTION_BLOCKLIST``
    # (apparent perf optimization) — that form iterates the live keys
    # view, and a future contributor adding key DELETION instead of value
    # replacement would hit ``RuntimeError: dictionary changed size
    # during iteration``.
    for key in event_dict.keys() & _REDACTION_BLOCKLIST:
        event_dict[key] = "<redacted>"
    return event_dict


def configure_logging(*, log_level: str = "info", json_output: bool = False) -> None:
    """Configure structlog for the application.

    ``log_level`` is the minimum log level (debug/info/warning/error/critical).
    ``json_output=True`` emits JSON; ``False`` emits pretty console format.

    Mutates the stdlib root logger handlers via ``handlers.clear()`` +
    ``addHandler(...)`` — first-call-wins. Subsequent calls (test fixtures
    that ``configure_logging`` between cases) clear-and-replace; any
    handler a third-party library may have parked on the root logger
    between two calls would be silently dropped. The autouse
    ``_reset_structlog_config`` fixture in ``test_logging.py`` is the
    canonical reconfigurator and only invokes ``structlog.reset_defaults()``
    plus a single ``configure_logging(...)`` re-call, so the contract holds
    today; a future fixture binding a stdlib handler before
    ``configure_logging`` would need to re-bind that handler after.
    """
    # Build the shared processor chain. Order matters here: ``merge_contextvars``
    # runs FIRST so contextvars-bound keys are present on the event dict before
    # the canonical processors below (``add_log_level``, ``add_logger_name``,
    # ``TimeStamper``) have a chance to overwrite same-named keys. The
    # canonical-processor overwrites are intentional — operator filters key
    # off ``level`` / ``timestamp`` and a caller-bound ``level="custom"``
    # would silently shadow them otherwise. The ``_redact_sensitive_keys``
    # backstop slots in between (after merge, before the canonical-overwrite
    # trio) so a contextvar-bound prompt key is also redacted before any
    # downstream renderer sees it; the position is intentional and the
    # ``_REDACTION_BLOCKLIST`` invariant pins that no blocklist entry
    # collides with a canonical-processor output key.
    #
    # In JSON mode we append ``dict_tracebacks`` so structlog converts
    # ``exc_info`` into a structured ``exception`` key for the JSONRenderer;
    # without it, ``logger.exception`` would render an opaque ``repr`` of
    # the exc_info tuple in production logs. In dev mode we omit the
    # processor because ConsoleRenderer already pretty-prints exceptions
    # itself (and structlog warns when ``format_exc_info`` is added on top
    # of it).
    #
    # ``StackInfoRenderer`` is intentionally OMITTED — it only acts when a
    # log call passes ``stack_info=True``, and no call site in the codebase
    # does (verified by ``grep -rnE "stack_info=" apps/backend/app``). Per
    # CLAUDE.md ADR-011 ("build only what the current feature requires"),
    # the no-op processor was dead weight on every log line. Re-add it
    # when a debug-time bind needs ``stack_info`` capture.
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        # Defense-in-depth redaction sits AFTER ``merge_contextvars`` so a
        # contextvar bind that accidentally carries prompt content is also
        # caught. The CLAUDE.md "never log message content" rule is the
        # primary contract; this processor is the infrastructure backstop.
        _redact_sensitive_keys,
        structlog.stdlib.add_log_level,
        # ``add_logger_name`` adds the ``logger`` field — kept (rather than
        # dropped as redundant noise) for jq ``.logger`` selectors when
        # grepping by module path during multi-feature debugging.
        structlog.stdlib.add_logger_name,
        # utc=True keeps log timestamps in lockstep with the project's
        # datetime.now(UTC) discipline (see CLAUDE.md). Without it,
        # structlog defaults to local time, producing tz-ambiguous lines.
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if json_output:
        # ``dict_tracebacks`` is the singleton ExceptionRenderer that ships
        # with structlog, but its default ``show_locals=True`` would
        # serialize every frame's locals into the JSON ``exception`` field
        # — and locals carrying ``messages`` / ``body`` / ``params`` would
        # bypass ``_redact_sensitive_keys`` (which only inspects TOP-LEVEL
        # event-dict keys). Construct an explicit ExceptionRenderer with
        # ``show_locals=False`` so frame locals are never serialized,
        # closing the CLAUDE.md "never log message content" leak surface.
        shared_processors.append(
            structlog.processors.ExceptionRenderer(
                structlog.tracebacks.ExceptionDictTransformer(show_locals=False),
            ),
        )
    shared_processors.append(structlog.processors.UnicodeDecoder())

    if json_output:
        renderer: structlog.typing.Processor = structlog.processors.JSONRenderer()
    else:
        # ConsoleRenderer's default ``exception_formatter`` is
        # ``RichTracebackFormatter(show_locals=True, ...)`` — the dev-mode
        # twin of the JSON-mode leak above. Construct it with
        # ``show_locals=False`` so dev tracebacks never render frame
        # locals carrying CLAUDE.md-banned message content.
        renderer = structlog.dev.ConsoleRenderer(
            exception_formatter=structlog.dev.RichTracebackFormatter(show_locals=False),
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        # ``stdlib.BoundLogger`` (not ``make_filtering_bound_logger``) so the
        # ``foreign_pre_chain`` below can route uvicorn/httpx/asyncio stdlib
        # records through the same processor stack and produce uniform JSON
        # output across native structlog and stdlib emitters. The trade-off
        # is per-call processor evaluation cost on debug-level lines that
        # would have been short-circuited by the filtering wrapper; for a
        # single-developer LAN service the cost is negligible vs the
        # uniformity benefit.
        wrapper_class=structlog.stdlib.BoundLogger,
        # ``cache_logger_on_first_use`` is INTENTIONALLY OMITTED. Setting
        # it to True freezes the bound logger on first ``get_logger()``
        # call, which means ``reset_defaults()`` (used in
        # tests/unit/core/test_logging.py) does NOT pick up the
        # reconfigured chain on already-imported module loggers. The perf
        # delta of the cache is sub-microsecond per call, well below the
        # operator-debugging cost of stale loggers when tests / dev
        # iteration reconfigure logging mid-run.
    )

    # foreign_pre_chain pipes stdlib-originated records (uvicorn, httpx,
    # asyncio) through the same processor stack so JSON output stays
    # uniform across native structlog and stdlib emitters.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())

    # Silence noisy third-party loggers. uvicorn.access duplicates
    # information that the RequestIdMiddleware request_completed line
    # already carries — and we don't want the unstructured access format
    # polluting JSON output.
    # This is one of the two approved uses of stdlib logging.getLogger
    # in the codebase (the other is the root-handler bind above); the
    # forbidden pattern is using stdlib loggers for application logs.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
