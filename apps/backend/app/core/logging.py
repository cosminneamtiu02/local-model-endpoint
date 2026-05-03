"""Structured logging configuration with structlog.

This module is the SOLE approved location in the codebase for
``logging.getLogger`` (used at the bottom to silence ``uvicorn.access``).
The CLAUDE.md "never use logging.getLogger" sacred rule covers
application code; this bridge to stdlib's logger registry is the
documented exception. All other code uses ``structlog.get_logger``.
"""

import logging
import sys

import structlog


def configure_logging(*, log_level: str = "info", json_output: bool = False) -> None:
    """Configure structlog for the application.

    Args:
        log_level: The minimum log level (debug, info, warning, error, critical).
        json_output: If True, output JSON. If False, output pretty console format.
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
        # ``cache_logger_on_first_use=True`` freezes the bound logger on
        # first ``get_logger()`` call. ``reset_defaults()`` (used in
        # tests/unit/core/test_logging.py) does NOT clear those frozen
        # per-module loggers; tests that re-configure logging mid-run and
        # expect already-imported modules' loggers to pick up the new
        # config will see stale loggers. Today no test does that, but the
        # trap is real — see test_logging.py docstring for the contract.
        cache_logger_on_first_use=True,
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
