"""Shared fixtures for inference-feature unit tests.

Centralizes the `_valid_kwargs()` factories and the canonical
test request_id so the three sibling test modules
(test_response_metadata, test_inference_response, test_ollama_chat_result)
don't drift their factories independently.
"""

import pytest

from app.schemas.wire_constants import UUID_REGEX

# Canonical UUID-shaped fixture id for inference-feature unit tests.
# Hoisted to a module constant so the import-time invariant assertion
# below pins it against the wire-contract regex, mechanically defeating
# silent drift between the fixture and ``UUID_PATTERN_STR`` (a future
# regex tightening that no longer matches this literal will fire here
# at collection time, not 16 silent green tests later).
_VALID_REQUEST_ID = "00000000-0000-4000-8000-000000000abc"
assert UUID_REGEX.match(_VALID_REQUEST_ID), (
    f"valid_request_id fixture ({_VALID_REQUEST_ID}) no longer matches the wire-contract"
    " UUID regex; tighten or update the fixture in lockstep with the regex."
)


@pytest.fixture
def valid_request_id() -> str:
    """UUID-shaped request_id matching the wire-contract regex.

    The regex is enforced by both ``RequestIdMiddleware`` and
    ``ProblemDetails.request_id``. The literal is hoisted to
    ``_VALID_REQUEST_ID`` so a regex-vs-literal drift fails at
    collection time (see the assertion at module scope).
    """
    return _VALID_REQUEST_ID


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
