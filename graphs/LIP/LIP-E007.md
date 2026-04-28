---
type: epic
id: LIP-E007
parent: LIP
title: Documentation & Contract Discoverability
status: verifiable
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

None. Both Epic-level questions raised at requirements-elicitation time were resolved during feature thickening:

- **OpenAPI exposure** — resolved by F001: both `/docs` (Swagger UI) and `/redoc` (Redoc UI) are exposed (FastAPI defaults retained). No production-disabling logic in v1 (no production/dev distinction; single deployment trusts local-network callers). README documents both URLs alongside `/openapi.json` (machine-readable contract source).
- **README location** — resolved by F001: project root `README.md` (replaces the post-bootstrap generic README). Project-root location is the canonical landing page for the repo; consumers cloning land here. Feature-scoped README would split discoverability since LIP has effectively one consumer-facing surface (the inference endpoint).

## Features

- [LIP-E007-F001](LIP-E007-F001.md) — README documenting the conceptual model (verifiable, p180)
- [LIP-E007-F002](LIP-E007-F002.md) — Working httpx-based example consumer integration snippet (verifiable, p190)
