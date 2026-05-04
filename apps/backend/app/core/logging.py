"""Structured logging configuration with structlog.

This module is the SOLE approved location in the codebase for
``logging.getLogger`` (used at the bottom to silence ``uvicorn.access``).
The CLAUDE.md "never use logging.getLogger" sacred rule covers
application code; this bridge to stdlib's logger registry is the
documented exception. All other code uses ``structlog.get_logger``.
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
    for key in event_dict.keys() & _REDACTION_BLOCKLIST:
        event_dict[key] = "<redacted>"
    return event_dict


def configure_logging(*, log_level: str = "info", json_output: bool = False) -> None:
    """Configure structlog for the application.

    ``log_level`` is the minimum log level (debug/info/warning/error/critical).
    ``json_output=True`` emits JSON; ``False`` emits pretty console format.
    """
    # Build the shared processor chain. Order matters here: ``merge_contextvars``
    # runs FIRST so contextvars-bound keys are present on the event dict before
    # the canonical processors below (``add_log_level``, ``add_logger_name``,
    # ``TimeStamper``) have a chance to overwrite same-named keys. The
    # canonical-processor overwrites are intentional — operator filters key
    # off ``level`` / ``timestamp`` and a caller-bound ``level="custom"``
    # would silently shadow them otherwise.
    #
    # In JSON mode we insert ``dict_tracebacks`` AFTER StackInfoRenderer so
    # structlog converts ``exc_info`` into a structured ``exception`` key for
    # the JSONRenderer; without it, ``logger.exception`` would render an
    # opaque ``repr`` of the exc_info tuple in production logs. In dev mode
    # we omit the processor because ConsoleRenderer already pretty-prints
    # exceptions itself (and structlog warns when ``format_exc_info`` is
    # added on top of it).
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
        structlog.processors.StackInfoRenderer(),
    ]
    if json_output:
        # ``dict_tracebacks`` is a singleton instance per structlog 25.x; if
        # upgraded to a factory, switch to
        # ``any(isinstance(p, type(structlog.processors.dict_tracebacks))
        # for p in processors)`` for the membership test in tests/lints.
        shared_processors.append(structlog.processors.dict_tracebacks)
    shared_processors.append(structlog.processors.UnicodeDecoder())

    if json_output:
        renderer: structlog.typing.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

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
    # This is the one approved use of stdlib logging.getLogger; the
    # forbidden pattern is using stdlib loggers for application logs.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
