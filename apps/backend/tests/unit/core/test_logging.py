"""Unit tests for configure_logging.

Closes the no-test gap flagged by Lane 13.4 (CLAUDE.md TDD sacred rule).
``configure_logging`` wires a 7-step processor chain, two renderer paths, a
stdlib bridge, and a uvicorn.access silencer; without coverage, any change to
the chain ships untested.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
import structlog
from structlog.testing import capture_logs

from app.core.logging import configure_logging

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _reset_structlog_config() -> Generator[None]:
    """Reset structlog defaults before AND after each test.

    structlog.configure(cache_logger_on_first_use=True) freezes the bound
    logger after first use; without a reset, a prior test's configuration
    leaks into the next. Resetting both before and after closes a hidden
    ordering coupling: without the post-yield reset, the LAST test in this
    file leaves structlog with whatever processor chain configure_logging
    last set, and subsequent test files inherit that state via the
    session-scoped event loop.
    """
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()


def test_configure_logging_sets_root_handler_level() -> None:
    configure_logging(log_level="warning", json_output=False)
    assert logging.getLogger().level == logging.WARNING


def test_configure_logging_silences_uvicorn_access_to_warning() -> None:
    configure_logging(log_level="info", json_output=False)
    # The exact level matters because uvicorn.access emits at INFO; pinning at
    # WARNING is the silencer.
    assert logging.getLogger("uvicorn.access").level == logging.WARNING


def test_configure_logging_round_trips_event_via_capture_logs() -> None:
    """A log call surfaces the event + structured kwargs via capture_logs."""
    # Note: structlog.testing.capture_logs() short-circuits the processor
    # chain by design (it captures what was *emitted*, not what was rendered),
    # so merge_contextvars is not exercised here. The contextvars-merge path
    # is separately covered by the integration tests that observe a
    # request_completed line carrying the middleware-bound request_id.
    configure_logging(log_level="info", json_output=False)
    logger = structlog.get_logger("test")
    with capture_logs() as captured:
        logger.info("smoke", k="v")
    assert any(evt.get("event") == "smoke" and evt.get("k") == "v" for evt in captured), captured


def test_configure_logging_json_mode_adds_dict_tracebacks() -> None:
    """JSON mode inserts dict_tracebacks for structured exception rendering."""
    configure_logging(log_level="info", json_output=True)
    processors = structlog.get_config()["processors"]
    # ``dict_tracebacks`` is a singleton ExceptionRenderer in structlog —
    # identity comparison locks the exact processor (avoids matching any
    # other ExceptionRenderer that may exist in the chain).
    assert structlog.processors.dict_tracebacks in processors, processors


def test_configure_logging_dev_mode_omits_dict_tracebacks() -> None:
    """Dev/console mode relies on ConsoleRenderer's own exception formatting."""
    configure_logging(log_level="debug", json_output=False)
    processors = structlog.get_config()["processors"]
    # Inverse of the JSON-mode assertion: console mode must NOT install
    # dict_tracebacks (ConsoleRenderer formats exceptions itself, and
    # structlog warns when format_exc_info is layered on top of it).
    assert structlog.processors.dict_tracebacks not in processors, processors


@pytest.mark.parametrize(
    "sensitive_key",
    ["messages", "content", "prompt", "tool_calls", "audios", "images"],
)
def test_redaction_processor_strips_sensitive_keys(sensitive_key: str) -> None:
    """Defense-in-depth backstop for CLAUDE.md prompt-content log ban.

    The redaction processor replaces values for known-sensitive keys with the
    ``"<redacted>"`` sentinel regardless of caller discipline. Tested in
    isolation against a synthetic event_dict because ``capture_logs()`` is
    documented to short-circuit the processor chain — the actual chain
    integration is verified by the membership check below
    (``test_redaction_processor_is_in_shared_processors``).
    """
    from app.core.logging import _redact_sensitive_keys

    event_dict = {sensitive_key: "secret-prompt-content", "event": "smoke"}
    result = _redact_sensitive_keys(None, "info", event_dict)
    assert result[sensitive_key] == "<redacted>"
    # Untouched non-sensitive keys must pass through verbatim.
    assert result["event"] == "smoke"


def test_redaction_processor_is_in_shared_processors() -> None:
    """The redaction processor MUST be in the configured chain or the
    isolation test above is meaningless. Drops to a membership check on the
    structlog config."""
    from app.core.logging import _redact_sensitive_keys

    configure_logging(log_level="info", json_output=False)
    processors = structlog.get_config()["processors"]
    assert _redact_sensitive_keys in processors, processors
