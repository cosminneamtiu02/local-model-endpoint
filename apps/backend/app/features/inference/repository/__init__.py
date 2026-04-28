"""Inference repository — the data-access boundary (Ollama HTTP client).

`OllamaClient` is the swap point for G1: when a future backend replaces
Ollama (vLLM, MLX, hosted), this module's surface is what gets renamed,
not every consumer that imports it. Consumers should import via the
package (`from app.features.inference.repository import OllamaClient`)
rather than per-file paths so the seam stays narrow.

``DEFAULT_TIMEOUT`` is intentionally NOT re-exported here; tests that
need to inspect the default reach for it via the per-file import
``from app.features.inference.repository.ollama_client import
DEFAULT_TIMEOUT`` so the production package surface stays minimal.
"""

from app.features.inference.repository.ollama_client import OllamaClient

__all__ = ["OllamaClient"]
