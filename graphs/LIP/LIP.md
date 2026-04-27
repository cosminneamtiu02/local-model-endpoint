---
type: project
slug: LIP
title: Local Inference Provider
status: outlined
---

## Short description

A single-machine FastAPI service that wraps a local Ollama daemon on a 16 GB M4 Mac Mini and exposes a stable backend-agnostic inference contract to up to four locally-networked consumer backend projects, with on-demand lifecycle and serial inference.

## Core idea

The Local Inference Provider is a FastAPI service that runs on a 16 GB M4 Mac Mini base, wraps a local Ollama daemon, and exposes a stable, backend-agnostic inference contract to up to four locally-networked consumer backend projects (one today, three more within twelve months) owned by one developer. The v1 deliverable enforces strictly serial inference at the service layer via `asyncio.Semaphore(1)` with bounded-waiter-count backpressure (HTTP 503), centralizes per-model knowledge in an in-process model registry, and runs on-demand — woken by an explicit consumer-issued wake call and self-shutting after 10 minutes of idle — so the Mini's memory remains available for desktop work whenever LLM is not actively in use. It is implemented natively (no Docker) inside the existing monorepo template's vertical-slice architecture, with Ollama running as a launchd-managed daemon configured for short-TTL model retention. The project intentionally ships only the architectural foundation for future per-project controls (quotas, structured logging, request tracing), not their implementation; trusts only callers on the local network; and is documented through auto-generated OpenAPI plus a human-written README so the developer can integrate future consumer projects against it without re-reading the source.

## Problem being solved

The four planned consumer backend projects each need LLM inference. Calling Ollama directly from each consumer creates three compounding problems: per-model operational knowledge (sampling defaults, capability flags, context limits) gets duplicated and silently drifts across consumer codebases; backend-tech obsolescence forces a future multi-consumer rewrite when Ollama is replaced by vLLM, MLX, or a hosted provider; and there is no single inspection surface for cross-project LLM debugging — a hallucination or slow response requires grepping multiple consumer projects' logs to triangulate. This service is the chokepoint that resolves all three by owning the inference contract, the model registry, and the future observability point on behalf of every consumer.

## Intended users

A single solo developer who builds, operates, and consumes this service via one to four owned consumer backend projects on the same Mac Mini or local network. There are no external users, no operations team, no co-maintainers, and no human end-users in the loop with respect to this service — end-users of the consumer projects never call this service directly.

## Known constraints

- Hardware fixed to M4 Mac Mini base, 16 GB unified memory, Apple Silicon ARM64, macOS only.
- Python 3.13 with `uv` as the dependency manager (template-mandated).
- FastAPI, Pydantic v2, asyncio, httpx, structlog as the core libraries (template-mandated).
- Ollama as the v1 inference backend; Gemma 4 E2B as the v1 model.
- On-demand FastAPI lifecycle; always-on Ollama daemon with `OLLAMA_KEEP_ALIVE=300s`; FastAPI self-shuts after 10 minutes idle.
- Native deployment via `uv` and `launchd` (no Docker).
- Local network only; no Internet exposure; no authentication beyond local-network trust.
- Solo developer; zero marginal spend.
- Vertical-slice template architecture with repurposed layer semantics for a no-database feature: `model/` holds Pydantic value-objects, `repository/` holds the Ollama HTTP client, `service/` holds inference orchestration, `router/` holds FastAPI endpoints.
- TDD discipline (red → green → refactor), one class per file, structured logging via `structlog`, configuration via `pydantic-settings`, errors via the DomainError hierarchy and `errors.yaml` system. CLAUDE.md's "Sacred Rules" and "Forbidden Patterns" are non-negotiable.
- Repository conventions are defined in `CLAUDE.md`. Feature bundles must not contradict `CLAUDE.md`.
- All code must be fully type-annotated. Pydantic models for data shapes. Pyright strict must pass.

## Rejected directions

- *Streaming responses (SSE / WebSockets / chunked JSON)* — buffered JSON keeps the contract simple and matches v1's batch-style consumer patterns; streaming is a future possibility, not a v1 deliverable.
- *Tool / function calling* — out of v1 scope; the request envelope's `metadata` placeholder leaves room for future addition without breaking the contract.
- *Multi-model routing within a single process* — one model loaded at a time fits the 16 GB Mini's RAM envelope; switching models is a manual configuration change.
- *Persistent queue (Redis, RabbitMQ, etc.)* — the in-memory `asyncio.Semaphore(1)` plus bounded waiter count is sufficient for ≤4 serial consumers.
- *Inference response caching* — caching introduces correctness questions (determinism, seed interaction) and storage decisions (keying, eviction) that do not fit the v1 surface area; deferred to G4's foundation.
- *Structured-log emission* — v1 ships only the metadata field shape as a pass-through; full logging is a future milestone.
- *Ops dashboard, frontend, or web UI of any kind* — backend-only project; HTTP endpoints plus structured JSON are the operator surface.
- *Authentication or authorization beyond local-network trust* — local-network reachability is the entire trust model.
- *`launchd` auto-start of the FastAPI service on Mac boot* — contradicts the on-demand lifecycle (G6).
- *In-process crash auto-recovery during a session* — explicit user choice; crashes surface to the consumer for manual investigation.
- *Generated client libraries* — OpenAPI plus README is sufficient; consumers codegen on their own side if they want.
- *Backend-swap stub or proof of swappability* — architectural decoupling (G1) is the deliverable; v1 does not deliver a second backend implementation as evidence.
- *Internet exposure or `0.0.0.0` binding* — explicit security stance, local-network only.
- *Docker or Docker Compose* — Docker Desktop's persistent daemon contradicts G6's "Mini free for desktop work" stance.
- *Per-project quotas, rate limits, or priorities* — architectural foundation only (G4); no v1 implementation.
- *macOS-side observability stack (Prometheus, OpenTelemetry, Grafana)* — local-only personal-use service; the complexity is mismatched to v1.
- *Portability to Linux, Windows, or non-Apple-Silicon hardware* — out of v1 scope per the deployment-target constraint.
- *Performance-measurement automation* — the brief's pre-elicitation homework is a one-time human activity, not a v1-deliverable feature.
- *Slim-backend-only template extraction* — meta-exercise about the template repository, deferred to a separate disambiguation pass with its own brainstorm.

## Success criteria

- **G1** — Consumer projects are decoupled from the inference backend; future swaps (Ollama → vLLM, MLX, cloud) require no consumer-code changes.
- **G2** — Per-model knowledge (sampling defaults, capability flags, context limits) lives in the service's in-process registry, not in consumers.
- **G3** — All inference traffic flows through a single observable point — the architectural foundation for future structured logging and tracing across consumer projects.
- **G4** — The request envelope and service architecture absorb future per-project controls (quotas, structured logging, request tracing) without breaking the contract.
- **G5** — The service sustains reliable serial inference on the 16 GB M4 Mini under the realistic load envelope (up to four serial consumers) without OOM, thrashing, or unbounded queue growth.
- **G6** — The service is on-demand, with its lifecycle driven by consumers via an explicit wake call and a 10-minute idle self-shutdown — not by the OS.
- **G7** — The service exposes its live operational state via HTTP (`/health` plus state-inspection endpoints for queue depth, model-loaded status, last-request timestamp) — without log parsing.
- **G8** — Consumer projects can integrate against this service via the auto-generated OpenAPI schema and a human-written README, without reading the service's source code.

## Scale & scope expectations

Single-machine deployment to one specific 16 GB M4 Mac Mini base. Local-network reachability only. Up to four consumer backend projects calling serially over HTTP, all owned by the same developer (one consumer today, three more anticipated within twelve months). One LLM model resident at a time (Gemma 4 E2B in v1). On-demand lifecycle: the FastAPI service is woken by an explicit consumer call and self-shuts after 10 minutes of no inference traffic; the Ollama daemon stays resident as a `launchd`-managed service with `OLLAMA_KEEP_ALIVE=300s`. v1 throughput is bounded by `asyncio.Semaphore(1)` — strictly serial inference at the service layer.
