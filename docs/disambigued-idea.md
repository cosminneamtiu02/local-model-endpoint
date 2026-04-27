# Disambiguated Idea: Local Inference Provider

## Refined Project Statement

The Local Inference Provider is a FastAPI service that runs on a 16 GB M4 Mac Mini base, wraps a local Ollama daemon, and exposes a stable, backend-agnostic inference contract to up to four locally-networked consumer backend projects (one today, three more within twelve months) owned by one developer. The v1 deliverable enforces strictly serial inference at the service layer via `asyncio.Semaphore(1)` with bounded-waiter-count backpressure (HTTP 503), centralizes per-model knowledge in an in-process model registry, and runs on-demand — woken by an explicit consumer-issued wake call and self-shutting after 10 minutes of idle — so the Mini's memory remains available for desktop work whenever LLM is not actively in use. It is implemented natively (no Docker) inside the existing monorepo template's vertical-slice architecture, with Ollama running as a launchd-managed daemon configured for short-TTL model retention. The project intentionally ships only the architectural foundation for future per-project controls (quotas, structured logging, request tracing), not their implementation; trusts only callers on the local network; and is documented through auto-generated OpenAPI plus a human-written README so the developer can integrate future consumer projects against it without re-reading the source.

## Stakeholders

The system has a single human stakeholder and a small, bounded set of programmatic consumer stakeholders. Every requirement in this document traces to one of them.

**Cosmin (solo developer).** Sole human stakeholder, owning every role end-to-end:

- *Builder:* writes the FastAPI service, schemas, model registry, and tests.
- *Operator:* runs the service on his M4 Mac Mini base (16GB unified memory), handles installs, env var configuration, restarts, monitoring, and recovery without an oncall rotation, ops team, or hosting provider.
- *Consumer-side developer:* writes the consumer backend projects that adopt this inference contract, experiencing the contract from both sides and serving as the only feedback loop on its ergonomics.
- *Maintainer and evolver:* owns future backend-swap decisions (Ollama → vLLM, MLX, cloud) and registry changes alone.

There is no co-maintainer, teammate, QA reviewer, family-member tester, or external collaborator. Operational responsibility, code review, and product direction all converge on one person.

**Consumer backend services.** Programmatic clients running on the same Mac Mini or local network, all owned by Cosmin, that call this service over HTTP for inference:

- *Today:* one consumer service exists — the PDF extractor.
- *12-month horizon:* up to four total consumer services, all owned by Cosmin, all local-network-only.

Consumer services have no human users in the loop with respect to *this* inference service. End-users of the consumer projects never call this service directly, never see its API, and impose no requirements on it that are not mediated through their consuming project.

## Goals

The project has eight top-level goals. Each is an outcome rather than an action, and each traces to one of Cosmin's role hats from the Stakeholders section.

### G1 — Consumer projects are decoupled from the inference backend.

Cosmin can swap Ollama for vLLM, MLX, or a cloud provider in the future without modifying any consumer code. *Sub-goals:* the request and response contract is owned by this service, not borrowed from any specific backend; logical model names like `"default-fast"` are resolved by an in-process model registry to backend-specific tags like `"gemma4:e2b"`, so backend tag changes never reach consumers. *Stakeholder:* Cosmin (consumer-side developer + maintainer).

### G2 — Per-model knowledge lives in the service, not in consumers.

Consumer projects send messages, a logical model name, and optional sampling overrides; they never need to know per-model sampling defaults, capability flags (text/image/audio), or context-window limits. *Sub-goals:* per-model sampling defaults baked into the in-process registry; capability flags and context-max accessible to the service so it can validate or route correctly. *Stakeholder:* Cosmin (consumer-side developer).

### G3 — All inference traffic flows through a single observable point.

This service is the single architectural location through which all inference requests across all consumer projects pass. It is the place where, in the future, structured logging, request tracing, and per-project attribution can be implemented. v1 ships only the *architectural foundation* — specifically the request envelope's `metadata` pass-through field — not the structured logging implementation itself. *Stakeholder:* Cosmin (operator).

### G4 — The service is ready to absorb future per-project controls without breaking the contract.

The request envelope and service architecture are designed so that quotas, rate limits, structured logging, and per-project attribution can be added later as additive changes without rewriting consumer-facing schemas. *Sub-goals:* the request `metadata` field is reserved for `project_id`, `request_id`, and `trace_id` (pass-through in v1); service composition supports inserting middleware-style controls between routing and inference. *Stakeholder:* Cosmin (maintainer).

### G5 — The service sustains reliable serial inference on the 16GB M4 Mini under known load.

Reliability here means no out-of-memory crashes, no thrashing, and no unbounded queue growth under the realistic operating envelope of up to four consumer projects calling serially over HTTP. *Sub-goals:* one model resident at a time, no model swapping in steady state; serial execution at the service layer via `asyncio.Semaphore(1)` regardless of HTTP-level concurrency; bounded waiter count with a 503 backpressure response when the queue is full. *Stakeholder:* Cosmin (operator).

### G6 — The service is on-demand, with its lifecycle driven by consumers rather than the OS.

The service does not auto-start on macOS boot. A consumer that needs inference is responsible for invoking an explicit wake-up step before issuing inference calls. *Sub-goals:*

- **No launchd auto-start of the FastAPI service.** The Mini's RAM and CPU are fully available for desktop use until inference is actively needed.
- **Explicit wake-up call separate from inference.** Consumers issue a dedicated wake action; the cold-start cost (Ollama model load + FastAPI warm-up dummy inference) is paid during wake, not during the first user-facing inference call.
- **No in-process auto-recovery on crash.** If the service crashes during an active session, the consumer receives an error and Cosmin investigates manually. The lifecycle stance is consumer-keeps-it-alive, not service-self-heals.
- **Ollama runs as a lightweight always-on launchd service.** Daemon idle cost is small (tens of MB resident). `OLLAMA_KEEP_ALIVE` is set to a short positive TTL of 300 seconds so the model itself unloads from RAM shortly after the last inference, freeing the 7.2GB the model occupies for desktop use. This replaces the brief's original `OLLAMA_KEEP_ALIVE=-1` setting; see the Resolved Contradictions section for the resolution.
- **FastAPI self-shuts after 10 minutes of no inference traffic.** When idle, the service exits cleanly; the next consumer to need inference re-wakes it.

*Stakeholder:* Cosmin (operator).

### G7 — The service exposes its live operational state via HTTP.

Cosmin can answer "what is this service doing right now" without parsing logs, by hitting HTTP endpoints. *Sub-goals:* a `/health` endpoint suitable for liveness and readiness probes; state-inspection endpoints sufficient to answer "is the model loaded into Ollama, what is the current semaphore queue depth, when did the last request complete." Mechanism is HTTP only — no Prometheus, OpenTelemetry, or external monitoring stack in v1. Live state is observable only while the service is running, which is a natural consequence of G6's on-demand lifecycle. *Stakeholder:* Cosmin (operator).

### G8 — Consumer projects can integrate against this service without reading its source code.

Documentation is sufficient on its own. *Sub-goals:* FastAPI's auto-generated OpenAPI schema is the canonical machine-readable contract, kept correct by Pydantic schemas being the single source of truth for request and response shapes; a human-written README documents the conceptual model — request envelope, semaphore semantics, model registry, error response shape, backpressure behavior, wake-up sequence; generated client libraries are not a v1 deliverable, so consumers either hand-roll httpx calls against the OpenAPI or run codegen on their own side. *Stakeholder:* Cosmin (consumer-side developer + maintainer).

## Underlying Needs (Five Whys)

Each goal in the previous section is grounded in a deeper underlying need that connects it to a concrete cost-if-absent. This section names that need explicitly so downstream skills can sanity-check whether a given solution actually serves the underlying motivation rather than only the stated goal.

**G1 — Decoupling from backend.** Underlying need: hedge against backend-tech obsolescence in a fast-moving inference ecosystem. Ollama, MLX, vLLM, and hosted APIs are all evolving rapidly; a service tightly coupled to Ollama's API surface would force a multi-consumer rewrite every time a backend swap is desirable. The decoupling pays for itself the first time a swap happens.

**G2 — Per-model knowledge encapsulation.** Underlying need: single source of truth for per-model operational knowledge so consumer projects do not duplicate or drift. If Gemma's sampling defaults live in four different consumer projects, one will silently diverge, behavior will inconsistently differ, and debugging "why does this consumer produce different output than another" becomes an archaeology problem.

**G3 — Single observability point.** Underlying need: cross-project LLM debuggability from one inspection surface. When LLM behavior is wrong, Cosmin should not have to grep four consumer projects' logs to figure out what was sent and what came back. Without G3, debugging cost scales linearly with consumer-project count.

**G4 — Future controls absorbable.** Underlying need: contract longevity. The request/response shape committed to in v1 must survive unchanged through future additions of quotas, structured logging, and per-project attribution. Without G4, v2 forces a breaking-change rewrite of every consumer project — which is exactly the cost G1 was meant to prevent.

**G5 — Reliability on M4.** Underlying need: operational confidence on resource-bounded hardware so the service is not an attention sink. Cosmin starts the service for a consumer's batch run and walks away. Without G5, every job becomes a babysitting session, which negates the productivity gain of having LLM available in consumer projects at all.

**G6 — On-demand lifecycle.** Underlying need: shared-use Mini economics. The Mini is also Cosmin's desktop and development machine; permanently locking 7.2GB of the model in RAM would consume 45% of the Mini's 16GB total, leaving inadequate memory for IDE, browser, and other desktop work. The on-demand stance keeps the Mini fully usable for non-LLM work whenever LLM is not actively needed.

**G7 — Live state via HTTP.** Underlying need: fast triage during an active session. When something feels off mid-session, Cosmin needs to immediately distinguish "service is processing, just slow" from "service is hung" from "service crashed silently" — without SSH, log inspection, or process probing. Without G7, mid-session intervention decisions are made by gut feel.

**G8 — Documented contract.** Underlying need: future-Cosmin-as-third-party-consumer ergonomics. When Cosmin starts consumer project number three six months from now, he will not remember this service's source; he will integrate the way he would integrate any third-party API — via docs and OpenAPI. Without G8, every new consumer project forces a re-loading of this service's internals into his head.

## Constraints

The project operates within a fixed and non-negotiable set of constraints, summarized below. Anything that could be re-decided in a future version of this project is not listed here; this section captures only what cannot move.

**Hardware.** M4 Mac Mini base, 16GB unified memory, Apple Silicon (ARM64). macOS is the only operating system. The service must work correctly on this exact hardware envelope. If a design implies a memory or compute requirement larger than the Mini can sustain, the design is wrong, not the constraint.

**Language and runtime.** Python 3.13, with `uv` as the dependency manager. Mandated by the monorepo template's discipline contract (CLAUDE.md "do not deviate" rule), to which Cosmin has pre-committed.

**Web framework and core libraries.** FastAPI, Pydantic v2, asyncio, httpx, structlog. Mandated by the template. No alternative web framework, no alternative HTTP client, no alternative logging library.

**Inference backend (v1).** Ollama running natively on macOS, with Gemma 4 E2B as the v1 model. G1 (decoupling) keeps these swappable post-v1, but for v1 these are the only paths exercised.

**Lifecycle posture.** Ollama daemon runs as a launchd-managed always-on service with `OLLAMA_KEEP_ALIVE=300s`. The FastAPI service is on-demand, woken by consumers via an explicit wake-up call, and self-shuts after 10 minutes of no inference traffic. No system-boot auto-start of the FastAPI service.

**Deployment shape.** Native — `uv`-managed virtualenv for the FastAPI service; `launchd`-managed Ollama daemon; no Docker. Docker Desktop's 1–2 GB persistent daemon would directly contradict G6's "Mini is free for desktop use when LLM isn't active" stance, and the portability benefit Docker would provide is irrelevant for a personal-use single-machine service deployed to exactly one Mini.

**Network.** Local network only. No Internet exposure. No authentication beyond what local-network trust provides; this is explicitly out of scope per the brief.

**Team and budget.** Solo developer. Zero marginal spend — hardware already owned, no cloud services in v1. Every line of code, every operational task, and every design decision converges on one person, which fixes the project's complexity budget.

**Template architecture (vertical slice with repurposed layers).** The inference capability lives in a single feature slice under `app/features/`. The template's four-layer structure is preserved but its layer meanings are repurposed for a no-database service: `model/` holds Pydantic envelope value-objects (Message, ModelParams, ModelInfo); `repository/` holds the Ollama HTTP client wrapper as the data-access boundary; `service/` holds the inference orchestration with the `asyncio.Semaphore(1)`; `router/` holds the FastAPI endpoints; `schemas/` holds request/response wire schemas. The template's import-linter layer rules (`router → service → repository → model`, no skipping) still apply to this repurposed layer mapping.

**Architecture discipline inherited from CLAUDE.md.** TDD (red → green → refactor) — no implementation written without a failing test first. One class per file. Vertical slices for features; features cannot import from other features. Structured logging via `structlog` only (no `print`, no f-string log messages). `pydantic-settings` for environment configuration only (no `os.environ` or `os.getenv`). DomainError hierarchy via the `errors.yaml` + generated code system; no `HTTPException` is raised. These are CLAUDE.md "Sacred Rules" and "Forbidden Patterns" — non-negotiable for this project as for every project built from this template.

## Quality Attributes

The non-functional requirements below apply at the project level. **Numerical targets in the Performance and Concurrency sections are provisional pre-measurement** — extrapolated from the brainstorm's stated 30–50 tok/s expectation and from public Apple-Silicon LLM-inference benchmarks for similarly-sized quantized models. They are concrete enough for downstream design but should be revised once Cosmin runs the brief's pre-elicitation homework (Ollama on the Mini, real prompts, real timings) before v1 implementation is finalized.

### Performance

**Wake-up latency.** From "consumer issues wake call" to "service is ready for first inference" — including Ollama daemon model load (when the model is unloaded), FastAPI startup, and the warm-up dummy inference. Target: under 15 seconds when the model is not currently loaded in Ollama; under 5 seconds when the Ollama daemon already has the model warm (within `KEEP_ALIVE=300s` TTL of the previous session). Hard ceiling: 30 seconds — beyond this, something is wrong (disk pressure, OS thermal throttling, etc.) and Cosmin investigates manually. *Provisional; revise after measurement.*

**Per-request inference latency.** P95 latency targets per representative prompt shape:

- *Light shape* — approximately 200 input tokens, 500 output tokens (typical interactive use): under 20 seconds.
- *Heavy shape* — approximately 500 input tokens, 1,000 output tokens (representative batch document-analysis call): under 40 seconds.

These targets derive from a midpoint estimate of 40 tok/s decode and ~600 tok/s prefill on M4 Apple Silicon, with safety margin for variance. Both must be revised after measurement.

**Throughput.** Bounded by `asyncio.Semaphore(1)` — strictly serial inference. Throughput equals one over per-request-latency. Not independently targeted; emerges from the latency target above.

### Reliability

**Backpressure behavior.** When the bounded waiter count exceeds the configured threshold (see Concurrency below), the service returns HTTP 503 with a structured DomainError response identifying "queue full." When per-request `asyncio.wait_for` exceeds the configured timeout, the service returns HTTP 504 with a structured DomainError response identifying "inference timeout." Both responses are deterministic, contract-documented, and consumable by client logic that wants to retry or escalate.

**Crash policy.** No in-process auto-recovery. If the FastAPI service crashes during an active session, in-flight requests fail with connection errors; the consumer surfaces an error to its caller; Cosmin investigates manually. There is no expectation of self-healing within a session; the service is consumer-kept-alive, not service-self-healing.

**Steady-state stability under known load.** Within an active session — FastAPI running, Ollama with the model loaded — the service exhibits no out-of-memory crashes, no thrashing, and no unbounded queue growth, for the realistic load envelope of up to four consumer projects calling serially over HTTP.

### Resource consumption

**Idle footprint.** When inactive — FastAPI shut down, the model unloaded by Ollama after its `KEEP_ALIVE=300s` TTL, only the Ollama daemon running — total resident memory across all inference-related processes is under 200 MB. CPU use is negligible. The Mini's memory and compute are fully available for desktop work.

**Active footprint.** When inference is active — FastAPI process running, Ollama with the model loaded — total resident memory is approximately 7.5 GB (about 7.2 GB for the loaded Gemma 4 E2B model in Ollama, plus tens of MB for the FastAPI process). The service must not exceed this envelope under realistic load; sustained operation above this number indicates a memory leak or unintended caching and is treated as a defect.

### Security

**Threat model.** Local-network trust only. The service trusts every caller reachable on the loopback interface and on the local network. There is no authentication, no authorization, and no input sanitization beyond what Pydantic validation provides for envelope shape. Binding is mandatory to `127.0.0.1` or to a local-network interface; binding to `0.0.0.0` is forbidden. Internet exposure is explicitly out of scope and explicitly not required.

### Observability

**Logging in v1.** Architectural placement only — the request envelope's `metadata` field is a pass-through for future `project_id`, `request_id`, `trace_id`. Actual structured-log emission is *explicitly not required* in v1.

**Live state in v1.** HTTP-introspectable via a `/health` endpoint and state-inspection endpoints exposing queue depth, model-loaded status, and last-request timestamp. Live state is observable only while the FastAPI service is running, which is a natural consequence of G6's on-demand lifecycle.

### Maintainability

TDD with the four mandatory test levels per CLAUDE.md (unit, integration, e2e, contract). One class per file. Vertical-slice independence enforced by import-linter contracts. Structured logging via `structlog`. Pyright strict and Schemathesis contract-test passes are build failures, not warnings. Maintainability target: future-Cosmin can change any single layer of the service (router, service, repository, model, schemas) without re-loading the whole project's internals.

### Portability

macOS arm64 only. Not portable to Linux, Windows, or Apple Silicon variants other than M-series Macs in v1 — *explicitly not required.* Future portability is a goal G1 enables (via backend swaps) but does not deliver.

### Concurrency and Backpressure

**Serial inference at the service layer.** `asyncio.Semaphore(1)` gates all inference calls regardless of HTTP-level concurrency. Multiple concurrent HTTP requests to the inference endpoint are accepted up to the bounded waiter count below, then rejected with 503.

**Backpressure threshold.** Maximum 4 waiters; beyond that, the service returns 503. With one request actively executing under the semaphore, this means the system holds at most five requests at once (one in-flight plus four waiting). For four consumer projects calling serially, this leaves comfortable headroom for one burst above the steady state before the threshold is hit. Worst-case in-queue wait for the fifth request is approximately five times p95 latency — about 85 seconds for the light shape, about 200 seconds for the heavy shape — which is acceptable for batch-style consumer patterns and unsuitable for interactive use; consumers can detect the queued state by request duration if they need to behave differently. *Provisional; revise after measurement.*

**Per-request timeout.** Server-side `asyncio.wait_for` is set to 180 seconds. Selected to accommodate the heavy-shape p95 (about 40 seconds) plus a safety margin for the worst-case realistic prompt shape (large input plus large output, up to roughly 4,000 tokens each), while still cutting off requests that have hung due to memory pressure, OS thermal throttling, or other pathological conditions. *Provisional; revise after measurement.*

## Project Boundary

This section enumerates what the v1 deliverable does and does not cover. It is the chokepoint at which scope creep is rejected; downstream skills (`requirements-elicitation`, `feature-elicitation`, `project-bootstrap`) refuse to take in-scope work that is not listed here, and refuse to drop out-of-scope items back into the build.

### In scope for v1

- A FastAPI service implementing the locked request envelope: `messages: list[Message]`, `model: str`, `params: ModelParams` (typed sampling — `temperature`, `top_p`, `top_k`, `max_tokens`, `stop`, `seed`, plus `think: bool = False`), and `metadata: dict[str, Any]` as a pass-through field.
- A single uvicorn-process deployment with on-demand lifecycle: woken by an explicit consumer-issued wake call, self-shuts after 10 minutes of no inference traffic.
- An explicit wake-up mechanism (separate from the inference call) that consumers invoke to start the service.
- A `/health` endpoint and additional state-inspection endpoints exposing queue depth, model-loaded status, and last-request timestamp (G7).
- An inference endpoint accepting POST with the envelope and returning a buffered (non-streaming) JSON response.
- A model registry implemented as an in-process metadata table mapping logical model names (e.g., `"default-fast"`) to backend tags (e.g., `"gemma4:e2b"`), with per-model sampling defaults, capability flags (text/image/audio), and context-window maxima.
- An `asyncio.Semaphore(1)` gating all inference calls; bounded waiter count with HTTP 503 backpressure response when the threshold is exceeded.
- A per-request server-side timeout via `asyncio.wait_for`, returning HTTP 504 with a structured DomainError on expiry.
- An async `httpx` client to the local Ollama daemon, with the daemon host configurable via a `pydantic-settings` field defaulting to `http://localhost:11434`.
- A startup warm-up dummy inference that loads the model into Ollama's memory before the service signals ready.
- The DomainError hierarchy and structured error response shape per CLAUDE.md (no `HTTPException`; errors flow through the `errors.yaml` + generated code system).
- `pydantic-settings`-based configuration for all environment variables.
- Auto-generated OpenAPI schema served from FastAPI as the canonical machine-readable contract (G8).
- A human-written README documenting the request envelope, semaphore semantics, model registry, error response shape, backpressure behavior, and wake-up sequence (G8).
- A `launchd` plist for the Ollama daemon configured with `OLLAMA_KEEP_ALIVE=300s`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_FLASH_ATTENTION=1`, and `OLLAMA_KV_CACHE_TYPE=q8_0`.
- A full TDD test suite at the four mandatory levels per CLAUDE.md: unit, integration, e2e, and contract (Schemathesis).

### Explicitly out of scope for v1

The following capabilities are not part of the v1 deliverable. Each is named explicitly because each is an adjacent capability a downstream reader could reasonably assume into scope, and naming them here prevents that drift.

- **Streaming responses.** No server-sent events, no WebSockets, no chunked JSON. All inference responses are buffered.
- **Tool / function calling.** Models that support tool use are configured to ignore tool inputs in v1; the contract has no tools field.
- **Multi-model routing within a single process.** One model loaded at a time; switching models is a manual configuration change, not a runtime decision.
- **Persistent queue.** No Redis, RabbitMQ, or filesystem queue; the in-memory `Semaphore(1)` and bounded waiter count are the only queue mechanism.
- **Inference response caching.** Identical `messages + model + params` re-runs the model; v1 has no cache layer. Caching is left as a future possibility under G4's foundation, not v1 work.
- **Structured-log emission.** v1 ships only the architectural placement: the request envelope's `metadata` field carries `project_id`, `request_id`, `trace_id` as a pass-through. Actual log emission, log shipping, log indexing, and log querying are out of scope.
- **Ops dashboard.** No web UI for operators; HTTP endpoints (G7) plus structured JSON responses are the operator surface.
- **Frontend or web UI of any kind.** This is a backend service; no template-frontend code is preserved in this project.
- **Authentication or authorization beyond local-network trust.** No API keys, no JWT, no OAuth, no per-project credentials. Local-network reachability is the entire trust model.
- **`launchd` auto-start of the FastAPI service on Mac boot.** The FastAPI service starts only when a consumer explicitly wakes it.
- **In-process crash auto-recovery during an active session.** A FastAPI crash surfaces to the consumer as a connection error; Cosmin investigates manually.
- **Generated client libraries.** Consumers either hand-roll `httpx` calls against the OpenAPI schema or run their own codegen.
- **Backend-swap stub or proof of swappability.** G1 establishes the architectural decoupling; v1 does not deliver a second backend implementation as evidence.
- **Internet exposure.** Binding to `0.0.0.0` is forbidden; the service binds to loopback or a local-network interface only.
- **Docker, Docker Compose, or container packaging.** The service runs as a native `uv`-managed Python process; the Ollama daemon runs as a native `launchd`-managed service.
- **Per-project quotas, per-project rate limits, per-project priorities.** Architectural foundation only (G4); no v1 implementation.
- **macOS-side observability stack.** No Prometheus, no OpenTelemetry, no Grafana, no external monitoring of any kind.
- **Portability to Linux, Windows, or non-Apple-Silicon hardware.** Future portability is a possibility G1 enables (via backend swaps) but does not deliver.
- **Performance-measurement automation.** The brief's pre-elicitation homework is a one-time human activity producing measurements that should be folded back into the Quality Attributes section; it is not a v1-deliverable feature.

## Resolved Contradictions

This section records contradictions surfaced between the brainstorm and the converged document, plus open questions from the brainstorm that this disambiguation pass closed, together with their resolutions.

### Contradiction — `OLLAMA_KEEP_ALIVE` value

The brainstorm specifies `OLLAMA_KEEP_ALIVE=-1` (model never unloads from Ollama's resident memory), which was coherent under the brainstorm's originally-implied always-on service deployment. Goal G6, formulated during Phase 2 of disambiguation, replaces that assumption with an on-demand lifecycle in which the FastAPI service is woken by consumers and self-shuts after 10 minutes of inactivity. Under this lifecycle, `KEEP_ALIVE=-1` would defeat the purpose of the on-demand stance — the model would remain pinned in roughly 7.2 GB of RAM long after the FastAPI service had already shut down.

**Resolution:** `OLLAMA_KEEP_ALIVE=300s` (5 minutes). The brainstorm's core invariant — *"one model resident, no swapping in the steady state"* — is preserved *within* an active session, since the 300-second TTL covers all intra-session gaps between requests. Once the FastAPI service self-shuts after 10 minutes of idle, the model unloads roughly 5 minutes later, freeing the Mini's RAM for desktop work. The replacement is recorded in the Constraints section under "Lifecycle posture" and reflected in the in-scope launchd plist under Project Boundary.

### Resolved open question — Template fit for v1 bootstrap

The brainstorm flagged this as an open question: *"Template fit — derive from existing monorepo template and delete frontend, or extract a slim backend-only template (this is the second backend-only service alongside the PDF extractor, so the slim template extraction is overdue)."*

**Resolution:** This project derives from the existing monorepo template; the downstream `project-bootstrap` skill will delete frontend bits during its run. The slim-backend-only template extraction is acknowledged as overdue but is deferred to a separate, future exercise — its own brainstorm and its own disambiguation pass — rather than being bundled into this project's scope. **Rationale:** the slim-template extraction is a meta-exercise about the template repository, not about this inference service. Entangling them would double immediate scope, complicate the test surface, and gate the inference service's deliverable behind unrelated work. Keeping them separate keeps each piece of work focused and well-bounded.
