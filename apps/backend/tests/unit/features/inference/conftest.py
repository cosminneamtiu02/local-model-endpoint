"""Shared fixtures for inference-feature unit tests.

Centralizes the `_valid_kwargs()` factories and the canonical
test request_id so the three sibling test modules
(test_response_metadata, test_inference_response, test_ollama_chat_result)
don't drift their factories independently.
"""

from typing import Final

import pytest

# Canonical UUID-shaped fixture id for inference-feature unit tests.
# Drift between this literal and the wire-contract regex is pinned by
# ``test_request_id_fixture_drift_guard.py`` (a sibling test module
# rather than an inline test function in this conftest, since pytest
# collects tests from ``test_*.py`` files by convention — embedding a
# test in conftest is undiscoverable to the standard ``find tests
# -name 'test_*.py'`` audit). ``Final[str]`` mirrors the discipline in
# ``apps/backend/app/core/config.py`` and ``tests/_helpers.py``.
VALID_REQUEST_ID: Final[str] = "00000000-0000-4000-8000-000000000abc"


@pytest.fixture
def valid_response_metadata_kwargs() -> dict[str, object]:
    """Canonical kwargs for ``ResponseMetadata`` construction.

    The ``request_id`` value comes from the module-level
    ``VALID_REQUEST_ID`` constant (rather than a separate fixture)
    because the constant has only one consumer site beyond this fixture
    — the drift-guard test in
    ``test_request_id_fixture_drift_guard.py`` — and an indirection
    fixture for a single-consumer constant adds noise without clarity.
    """
    return {
        "model": "gemma-4-e2b",
        "prompt_tokens": 12,
        "completion_tokens": 34,
        "request_id": VALID_REQUEST_ID,
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
