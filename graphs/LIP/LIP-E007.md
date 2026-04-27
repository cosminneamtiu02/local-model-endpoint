---
type: epic
id: LIP-E007
parent: LIP
title: Documentation & Contract Discoverability
status: not-started
priority: 70
dependencies: [LIP-E001, LIP-E002, LIP-E003, LIP-E004, LIP-E005, LIP-E006]
---

## Short description

The contract is documented for consumer projects: auto-generated OpenAPI plus a human-written README covering the conceptual model, error responses, backpressure behavior, and lifecycle.

## Description

This epic delivers the deliverable that lets future-Cosmin start a new consumer project without re-reading the inference service's source code. The auto-generated OpenAPI schema served by FastAPI is the canonical machine-readable contract — its accuracy is enforced by Pydantic schemas being the single source of truth for request and response shapes. A human-written README documents what OpenAPI cannot — the conceptual model: what the request envelope means, how `params` overrides registry defaults, what semaphore semantics imply for client behavior under load, what the structured error responses signal, the launch-and-poll-`/health` wake-up pattern, the 10-minute idle-shutdown behavior, and the prerequisite that Ollama is running as a `launchd` service. A working consumer integration snippet (httpx-based) anchors the README so consumers have a concrete starting point.

## Rationale

This epic implements G8 (consumer projects integrate without reading source) directly. It is separate from every other epic because docs cover the system as a whole and would otherwise risk under-investment if bundled into any single epic — bundling docs into the inference happy path (LIP-E001), for example, would make the README's lifecycle section invisible until LIP-E005's work was complete.

## Boundary

In scope: the README content covering the conceptual model — request envelope, model registry, sampling defaults and overrides, error response shapes and HTTP status codes, semaphore + queue depth + timeout semantics, on-demand lifecycle, Ollama daemon prerequisites; a working `httpx`-based consumer integration snippet. Out of scope: generated client libraries (rejected); a formal API versioning policy (not v1 — versioning is a future concern); per-language consumer docs (out of v1 — Python is the only consumer language).

## Open questions

*This list is not exhaustive. Additional questions may surface during feature elicitation.*

- Whether OpenAPI is exposed at `/docs` (Swagger UI), `/redoc`, both, or neither in v1 requires a decision; the FastAPI default exposes both.
- Where the README lives in the monorepo — at the feature slice's root (`apps/backend/app/features/<feature>/README.md`) or at the project root — requires a decision matching CLAUDE.md conventions.
