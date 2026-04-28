---
type: epic
id: LIP-E006
parent: LIP
title: Operational Visibility
status: verifiable
priority: 60
dependencies: [LIP-E001, LIP-E004]
---

## Short description

HTTP endpoints exposing live operational state — `/health` for liveness/readiness plus state-inspection endpoints reporting queue depth, model-loaded status, and last-request timestamp.

## Description

This epic delivers the operator-facing surface that lets the developer answer "what is this service doing right now" without parsing logs or probing processes. A `/health` endpoint serves liveness and readiness signals — liveness returns 200 if the process is alive, readiness returns 200 only after the warm-up dummy inference has completed (signalled by LIP-E005). One or more state-inspection endpoints expose the current semaphore queue depth (sourced from LIP-E004), whether Ollama currently has the model loaded (sourced via a probe through LIP-E003), and the timestamp of the most recent inference request. All endpoints return structured JSON; no HTML, no operator dashboard, no Prometheus exposition format.

## Rationale

This epic implements G7 (live operational state via HTTP) directly. Without it, mid-session intervention decisions (is the service hung, queued, processing, or crashed?) are made by gut feel. It is separate from inference (LIP-E001) and lifecycle (LIP-E005) because the audience is the operator hat reading state, not the consumer-side-developer hat invoking inference or the launching consumer waiting on readiness. Different responsibilities and different failure modes — a state-inspection endpoint should never block; an inference endpoint legitimately may.

## Boundary

In scope: the `/health` endpoint with liveness and readiness semantics; one or more state-inspection endpoints reporting queue depth, model-loaded status, and last-request timestamp as structured JSON; the in-process state-tracking required to populate these endpoints. Out of scope: structured-log emission (out of v1 scope entirely); Prometheus, OpenTelemetry, or external monitoring (out of v1 scope); a web UI dashboard (out of v1 scope); altering behavior based on state — e.g., self-restarting on degraded state, rejected by G6's no-auto-recovery stance.

## Open questions

None. All three Epic-level questions raised at requirements-elicitation time were resolved during feature thickening:

- **State-inspection endpoint structure** — resolved by F002: single consolidated `GET /state` returning all live operational state in one structured-JSON response. Single round-trip is operator-friendly; ≤4-consumer load doesn't benefit from selective fetching; one OpenAPI entry instead of three.
- **`/health` path convention** — resolved by F001: single `GET /health` endpoint with HTTP-status-as-readiness-signal (200 = ready; 503 = not-ready; connection-refused = down). Kubelet's separate `/health/live` and `/health/ready` paths are over-engineered for a personal local-network single-machine service. The single-endpoint design conveys all three observable states cleanly via HTTP status alone.
- **Ollama model-loaded probe latency** — resolved by F002: probed on every `/state` request (no TTL cache). Ollama's `/api/ps` is sub-100 ms locally; ≤4 consumers + occasional operator curls produce nowhere near enough load to warrant caching. The Ollama probe is best-effort — failure produces `ollama_reachable: false` + empty `ollama_loaded_models`, never a 5xx.
