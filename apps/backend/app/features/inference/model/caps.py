"""Shared DoS caps for the inference feature.

Single source of truth for the operational thresholds that bound a single
multimodal payload (per-part) and the wire envelopes that wrap it (request
metadata, response content). Multiple sibling files derived their own
literals from these numbers — duplicating them invited drift the moment
one threshold moved without the others, so they live here and are imported.
"""

from typing import Final

# 128 KiB per text part. Comfortably above any realistic single-turn prompt
# within Gemma's 128K-token context at ~4 chars/token; far below uvicorn's
# memory-pressure territory on the 16 GB M4 host.
TEXT_PART_MAX_CHARS: Final[int] = 131072

# 20 MiB per base64 blob (≈ 15 MB binary). Covers practical voice clips and
# images; longer media belongs in a streaming-upload path, not a single
# inline JSON body.
BASE64_MEDIA_MAX_CHARS: Final[int] = 20_971_520

# 2 KiB per URL. Bounds long-link DoS while staying above any realistic
# https URL.
URL_MAX_CHARS: Final[int] = 2048

# Upper bound on the response content size held in memory. ``ModelParams.max_tokens``
# has no project-level cap (consumer-supplied; ``gt=0`` only), so a misconfigured
# ``max_tokens=10_000_000`` could otherwise let Ollama generate an unbounded blob
# that lands in the frozen ``OllamaChatResult`` value-object. 1 MiB of text is
# far above any realistic Gemma 4 E2B output (128K tokens ≈ ~512K chars) and
# below memory-pressure territory on the 16 GB M4 host. Belt-and-suspenders
# alongside the sibling string caps (``TextContent.text``, ``ImageContent.url``).
CONTENT_MAX_LENGTH: Final[int] = 1_048_576

# Per-string cap for InferenceRequest metadata values. Bounds payload size
# symmetrically with Message string-content limits and prevents
# ``{"x": "<10MiB string>"}``-style memory amplification on the LAN-trusted-
# but-not-infallible consumer path. The validator walks nested lists/dicts
# so a consumer cannot bypass the cap by wrapping a long string in a
# one-element list or a single-key dict.
METADATA_VALUE_MAX_LENGTH: Final[int] = 4096

# Per-key cap for InferenceRequest metadata. 64 chars is a comfortable
# ceiling for any sensible attribution / project-tag key while bounding the
# third orthogonal DoS axis (key length) on the metadata path.
METADATA_KEY_MAX_LENGTH: Final[int] = 64

# Cap on the logical ``model`` name string. Same logical name flows in
# (``InferenceRequest.model``) and out (``ResponseMetadata.model``), so the
# bound must be symmetric — keeping it here means a future cap bump on the
# request side automatically tightens the response side too.
MODEL_NAME_MAX_LENGTH: Final[int] = 128
