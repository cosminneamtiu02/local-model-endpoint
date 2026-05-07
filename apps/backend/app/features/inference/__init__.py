"""Inference feature.

Public surface: re-export the swap-point class so api/ wiring imports
from the feature root rather than reaching into internals. As more
public types arrive (router, lifespan resource factory), they are
added here.

LIP-E001-F002 lockstep: when the inference router lands, its consumer-
facing wire schemas (``InferenceRequest``, ``InferenceResponse``,
``ResponseMetadata``) MUST be re-exported from this module so router
modules under ``app.api`` import from the feature root. The
``api-uses-inference-feature-root`` import-linter contract at
``apps/backend/architecture/import-linter-contracts.ini`` forbids
``app.api -> app.features.inference.schemas`` transitively; the feature-
root re-export is the project's chosen escape (mirroring the existing
``OllamaClient`` re-export above), NOT an ``ignore_imports`` line on the
contract. Pinning the convention here closes the "two ways to do each
thing" decision before the LIP-E001-F002 PR has to make it ad-hoc.
"""

from app.features.inference.repository import OllamaClient

__all__ = ["OllamaClient"]
