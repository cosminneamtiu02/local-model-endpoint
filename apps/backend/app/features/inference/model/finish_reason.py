"""FinishReason — public LIP finish-reason vocabulary.

Single source of truth for the three reasons an inference call can end:
`"stop"` and `"length"` are produced by the adapter from Ollama's
`done_reason`; `"timeout"` is set by LIP-E004-F003 when its
`asyncio.wait_for` budget elapses around an inference call.
"""

from typing import Literal

type FinishReason = Literal["stop", "length", "timeout"]
