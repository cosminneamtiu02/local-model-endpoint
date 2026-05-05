"""Unit tests for ``app.core.logging``.

Verifies ``configure_logging`` wires the 7-step processor chain, both
renderer paths (JSON + console), the stdlib bridge for foreign loggers,
and the uvicorn.access silencer; the redaction processor backstop for
the CLAUDE.md no-prompt-content rule is exercised against the live
``_REDACTION_BLOCKLIST`` source so the parametrize cannot drift behind
new entries.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
import structlog
from structlog.testing import capture_logs

from app.core.logging import _REDACTION_BLOCKLIST as _REDACTION_BLOCKLIST_SOURCE
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
    # Two-step assert (membership then field) gives pytest's introspection
    # an actionable diff: a single ``any(... and ...)`` would only show
    # "False" on failure, hiding whether the event was missing, the kwarg
    # was wrong, or a second event shadowed it.
    matching = [evt for evt in captured if evt.get("event") == "smoke"]
    assert len(matching) == 1, captured
    assert matching[0].get("k") == "v"


def test_configure_logging_json_mode_adds_exception_renderer() -> None:
    """JSON mode inserts an ExceptionRenderer for structured exception rendering.

    Class-membership rather than identity check because the production
    config builds a fresh ``ExceptionRenderer(ExceptionDictTransformer(
    show_locals=False))`` — NOT the ``structlog.processors.dict_tracebacks``
    singleton, which would default ``show_locals=True`` and leak frame
    locals carrying CLAUDE.md-banned message content into the JSON
    ``exception`` field.
    """
    configure_logging(log_level="info", json_output=True)
    processors = structlog.get_config()["processors"]
    assert any(isinstance(p, structlog.processors.ExceptionRenderer) for p in processors), (
        processors
    )


def test_configure_logging_dev_mode_omits_exception_renderer() -> None:
    """Dev/console mode relies on ConsoleRenderer's own exception formatting."""
    configure_logging(log_level="debug", json_output=False)
    processors = structlog.get_config()["processors"]
    # Inverse of the JSON-mode assertion: console mode must NOT install an
    # ExceptionRenderer (ConsoleRenderer formats exceptions itself via the
    # explicit show_locals=False RichTracebackFormatter passed to it).
    assert not any(isinstance(p, structlog.processors.ExceptionRenderer) for p in processors), (
        processors
    )


def test_configure_logging_json_mode_disables_show_locals() -> None:
    """JSON-mode ExceptionRenderer is constructed with ``show_locals=False``.

    Defends the CLAUDE.md "never log message content" rule: ``show_locals=True``
    (the structlog default for ``dict_tracebacks``) would serialize every
    frame's locals into the ``exception`` field, bypassing
    ``_redact_sensitive_keys`` which only inspects TOP-LEVEL keys. A future
    refactor that re-uses the ``dict_tracebacks`` singleton would silently
    re-enable the leak; this test pins the explicit-construction contract.
    """
    configure_logging(log_level="info", json_output=True)
    processors = structlog.get_config()["processors"]
    renderers = [p for p in processors if isinstance(p, structlog.processors.ExceptionRenderer)]
    assert len(renderers) == 1, processors
    # The transformer is stored on the ExceptionRenderer as
    # ``format_exception``; reading the inner ``show_locals`` attribute
    # is implementation-coupled but is the cheapest pin against the
    # show_locals=True regression. structlog 25.5 stub-types the slot
    # as the abstract ``ExceptionTransformer`` protocol (no
    # ``show_locals``), so the suppression below is the documented
    # escape hatch for the protocol-vs-concrete-impl gap.
    transformer = renderers[0].format_exception
    assert transformer.show_locals is False  # pyright: ignore[reportAttributeAccessIssue]


# Reading the parametrize from the source frozenset prevents drift: a new
# entry added to ``_REDACTION_BLOCKLIST`` is automatically exercised here
# without an extra hand edit. ``sorted`` keeps the parametrize id alphabet
# stable across runs (frozensets have insertion-order-dependent iteration).
@pytest.mark.parametrize("sensitive_key", sorted(_REDACTION_BLOCKLIST_SOURCE))
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


def test_redaction_processor_redacts_contextvar_bound_message_content(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Defense-in-depth contract: contextvar-bound prompt content is redacted
    on the rendered JSON line (not just on the synthetic event_dict above).

    Regression guard: a future refactor that moves ``_redact_sensitive_keys``
    BEFORE ``merge_contextvars`` (e.g. for performance) would silently break
    contextvar redaction while leaving every existing test green
    (``test_redaction_processor_strips_sensitive_keys`` calls the processor
    directly, never via the chain). This test exercises the full chain by
    binding via ``bind_contextvars`` and asserting the rendered JSON has
    the sentinel — which only happens if the redaction processor sees the
    contextvar-merged value.
    """
    structlog.contextvars.bind_contextvars(
        messages=[{"role": "user", "content": "SECRET-PROMPT-MARKER-12345"}],
    )
    try:
        configure_logging(log_level="info", json_output=True)
        logger = structlog.get_logger("test")
        logger.info("smoke")
        out = capsys.readouterr().out
        assert "<redacted>" in out, out
        assert "SECRET-PROMPT-MARKER-12345" not in out, out
    finally:
        structlog.contextvars.clear_contextvars()
