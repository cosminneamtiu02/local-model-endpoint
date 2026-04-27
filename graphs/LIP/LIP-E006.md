---
type: epic
id: LIP-E006
parent: LIP
title: Operational Visibility
status: not-started
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

*This list is not exhaustive. Additional questions may surface during feature elicitation.*

- The exact paths and structures of state-inspection endpoints (one big `/state`, or several focused endpoints like `/state/queue`, `/state/model`, `/state/last-request`) is to be decided during feature thickening.
- Whether `/health` follows the kubelet liveness/readiness probe convention (separate paths) or a single endpoint with structured fields requires a decision.
- Whether the model-loaded probe to Ollama is performed on every state-inspection request (potentially adding latency) or cached with a short TTL needs a design decision.
