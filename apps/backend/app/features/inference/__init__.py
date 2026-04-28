"""Inference feature.

LIP-E001-F001 ships the Pydantic value-objects (`model/`) and wire
schemas (`schemas/`). LIP-E003-F001 ships the Ollama HTTP client
(`repository/ollama_client.py`). The orchestrator (`service/`) and
router (`router/`) land with LIP-E001-F002 and downstream features.

Public surface: re-export the swap-point class so api/ wiring imports
from the feature root rather than reaching into internals. As more
public types arrive (router, lifespan resource factory), they are
added here.
"""

from app.features.inference.repository import OllamaClient

__all__ = ["OllamaClient"]
