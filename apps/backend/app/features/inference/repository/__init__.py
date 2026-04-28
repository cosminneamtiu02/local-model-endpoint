"""Inference repository — the data-access boundary (Ollama HTTP client).

`OllamaClient` is the swap point for G1: when a future backend replaces
Ollama (vLLM, MLX, hosted), this module's surface is what gets renamed,
not every consumer that imports it. Consumers should import via the
package (`from app.features.inference.repository import OllamaClient`)
rather than per-file paths so the seam stays narrow.
"""

from app.features.inference.repository.ollama_client import (
    DEFAULT_TIMEOUT,
    OllamaClient,
)

__all__ = [
    "DEFAULT_TIMEOUT",
    "OllamaClient",
]
