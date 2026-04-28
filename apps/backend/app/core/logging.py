"""Structured logging configuration with structlog."""

import logging
import sys

import structlog


def configure_logging(*, log_level: str = "info", json_output: bool = False) -> None:
    """Configure structlog for the application.

    Args:
        log_level: The minimum log level (debug, info, warning, error, critical).
        json_output: If True, output JSON. If False, output pretty console format.
    """
    # Build the shared processor chain. In JSON mode we insert
    # `dict_tracebacks` AFTER StackInfoRenderer so structlog converts
    # `exc_info` into a structured `exception` key for the JSONRenderer;
    # without it, `logger.exception` would render an opaque `repr` of the
    # exc_info tuple in production logs. In dev mode we omit the processor
    # because ConsoleRenderer already pretty-prints exceptions itself
    # (and structlog warns when `format_exc_info` is added on top of it).
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
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
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
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
    # information that the request-id middleware (and a future
    # request.completed line) already carries — and we don't want
    # the unstructured access format polluting JSON output.
    # This is the one approved use of stdlib logging.getLogger; the
    # forbidden pattern is using stdlib loggers for application logs.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
