> **Historical brainstorm.** This document captures the pre-disambiguation
> brief. The current authoritative specification is
> [docs/disambiguated-idea.md](disambiguated-idea.md). Some details here
> (e.g. KEEP_ALIVE=-1, open questions, deployment-shape uncertainty)
> are intentionally superseded.

Idea brief: Local Inference Provider service
Concept. A FastAPI service running on my M4 Mac Mini (16GB) that wraps Ollama and exposes a stable inference contract to my other local backend projects. One model loaded at a time (Gemma 4 E2B initially), serial execution via asyncio.Semaphore(1), buffered HTTP responses, no streaming, no async jobs.
Why this exists over calling Ollama directly. Stable internal contract decoupled from Ollama's API surface (forward compatibility for backend swaps — vLLM, MLX, cloud), per-model sampling defaults so consumer projects don't need model-specific knowledge, foundation for future per-project quotas and structured logging, single observability point for inference across projects.
Hardware envelope. M4 Mini base, 16GB unified memory, ~120 GB/s bandwidth. Gemma 4 E2B (7.2GB on disk, 2.3B effective params, 128K context, multimodal text+image+audio). Expected 30–50 tok/s decode (must verify on real hardware before sizing timeouts). OLLAMA_KEEP_ALIVE=-1, OLLAMA_NUM_PARALLEL=1, OLLAMA_MAX_LOADED_MODELS=1, OLLAMA_FLASH_ATTENTION=1, OLLAMA_KV_CACHE_TYPE=q8_0. One model resident, no swapping in the steady state.
Request envelope (locked).

messages: list[Message] — always a list, role + content
model: str — logical name resolved through service-side registry to backend tag
params: ModelParams — typed sampling params (temperature, top_p, top_k, max_tokens, stop, seed) plus think: bool = False
metadata: dict[str, Any] — placeholder for future logging fields (project_id, request_id, trace_id), pass-through for now

Architecture (locked).

Single uvicorn process
asyncio.Semaphore(1) gating all inference calls
Bounded waiter count → 503 when queue full
Per-request server-side timeout via asyncio.wait_for
httpx client to local Ollama on port 11434
Model registry as in-process metadata table: per-model sampling defaults + capability flags + context max
Service warms model with dummy inference on startup
Buffered (non-streaming) JSON responses

Out of scope for v1. Streaming responses, tool/function calling, multi-model routing, persistent queue, structured logging implementation (field shape only), ops dashboard, frontend, authentication beyond local network trust.
Open questions for elicitation to resolve.

Backpressure threshold — max waiters before 503, given measured tok/s and acceptable wait time
Model identifier in requests — logical name ("default-fast") vs literal Ollama tag ("gemma4:e2b")
metadata field shape — typed contract from day one vs free-form dict[str, Any] migrated later
Deployment shape — native binary vs Docker (Ollama itself runs natively on macOS, but the FastAPI service could go either way)
Template fit — derive from existing monorepo template and delete frontend, or extract a slim backend-only template (this is the second backend-only service alongside the PDF extractor, so the slim template extraction is overdue)

Pre-elicitation homework (must do first). Stand up Ollama on the Mini, pull gemma4:e2b, run with the env vars above, time real requests with realistic prompt sizes. Use measured tok/s and p95 latency to size the queue depth and timeout in elicitation, not extrapolated numbers.

That's the artifact. Take it to idea-disambiguation next, not brainstorming. And do the homework before the skill runs — elicitation grounded in real numbers is worth ten times the same elicitation grounded in guesses.
