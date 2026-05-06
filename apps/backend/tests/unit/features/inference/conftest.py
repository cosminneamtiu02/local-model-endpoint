"""Shared fixtures for inference-feature unit tests.

Centralizes the `_valid_kwargs()` factories and the canonical
test request_id so the three sibling test modules
(test_response_metadata, test_inference_response, test_ollama_chat_result)
don't drift their factories independently.
"""

import pytest

# Canonical UUID-shaped fixture id for inference-feature unit tests.
# Drift between this literal and the wire-contract regex is pinned by
# ``test_request_id_fixture_drift_guard.py`` (a sibling test module
# rather than an inline test function in this conftest, since pytest
# collects tests from ``test_*.py`` files by convention — embedding a
# test in conftest is undiscoverable to the standard ``find tests
# -name 'test_*.py'`` audit).
VALID_REQUEST_ID = "00000000-0000-4000-8000-000000000abc"


@pytest.fixture
def valid_request_id() -> str:
    """UUID-shaped request_id matching the wire-contract regex.

    The regex is enforced by both ``RequestIdMiddleware`` and
    ``ProblemDetails.request_id``. The literal is hoisted to module
    scope as ``VALID_REQUEST_ID`` so the drift-guard test module can
    import and assert against it without duplicating the value.
    """
    return VALID_REQUEST_ID


@pytest.fixture
def valid_response_metadata_kwargs(valid_request_id: str) -> dict[str, object]:
    """Canonical kwargs for ``ResponseMetadata`` construction."""
    return {
        "model": "gemma-4-e2b",
        "prompt_tokens": 12,
        "completion_tokens": 34,
        "request_id": valid_request_id,
        "latency_ms": 250,
        "queue_wait_ms": 5,
        "finish_reason": "stop",
        "backend": "ollama",
    }


@pytest.fixture
def valid_ollama_chat_result_kwargs() -> dict[str, object]:
    """Canonical kwargs for ``OllamaChatResult`` construction."""
    return {
        "content": "hello",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "finish_reason": "stop",
    }
