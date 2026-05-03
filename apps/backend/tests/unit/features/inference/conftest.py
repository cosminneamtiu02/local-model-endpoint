"""Shared fixtures for inference-feature unit tests.

Centralizes the `_valid_kwargs()` factories and the canonical
test request_id so the three sibling test modules
(test_response_metadata, test_inference_response, test_ollama_chat_result)
don't drift their factories independently.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def valid_request_id() -> str:
    """UUID-shaped request_id matching the wire-contract pattern enforced by
    both the middleware and ProblemDetails.request_id."""
    return "00000000-0000-4000-8000-000000000abc"


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
