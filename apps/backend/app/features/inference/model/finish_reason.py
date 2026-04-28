"""FinishReason — public LIP finish-reason vocabulary.

Single source of truth for the three reasons an inference call can end:
``"stop"`` and ``"length"`` come from Ollama's ``done_reason``;
``"timeout"`` is reserved for callers that wrap an inference call in a
timeout budget.
"""

from typing import Literal

type FinishReason = Literal["stop", "length", "timeout"]
