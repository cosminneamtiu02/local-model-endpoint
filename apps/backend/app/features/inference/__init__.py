"""Inference feature.

Public surface: re-export the swap-point class so api/ wiring imports
from the feature root rather than reaching into internals. As more
public types arrive (router, lifespan resource factory), they are
added here.
"""

from app.features.inference.repository import OllamaClient

__all__ = ["OllamaClient"]
