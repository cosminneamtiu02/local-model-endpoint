"""FinishReason — public LIP finish-reason vocabulary.

Single source of truth for the three reasons an inference call can
end. Used by both the adapter-internal `OllamaChatResult` (LIP-E003-F002)
and the public `ResponseMetadata` wire schema (LIP-E001-F001), so the
two type definitions cannot drift.

`"stop"` and `"length"` are produced by the adapter from Ollama's
`done_reason`; `"timeout"` is set by LIP-E004-F003 when its
`asyncio.wait_for` budget elapses around an inference call.
"""

from typing import Literal

type FinishReason = Literal["stop", "length", "timeout"]
