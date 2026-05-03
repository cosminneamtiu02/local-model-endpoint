"""Shared per-content-part DoS caps.

Single source of truth for the operational thresholds that bound a single
multimodal payload. Multiple sibling files derived their own literals from
these numbers — duplicating them invited drift the moment one threshold
moved without the others, so they live here and are imported.
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
