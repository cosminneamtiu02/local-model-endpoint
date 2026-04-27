---
type: epic
id: LIP-E001
parent: LIP
title: Inference Contract & Happy Path
status: partially-detailed
priority: 10
dependencies: []
---

## Short description

The user-visible inference behavior — request envelope in, model output JSON out — wired through a FastAPI router and a service-layer orchestrator that delegates to the model registry and the backend adapter.

## Description

This epic delivers the project's core deliverable: the HTTP surface and the orchestration code path that handle a single inference request from receipt to response. A consumer issues a `POST` with the request envelope (`messages: list[Message]`, `model: str` as a logical name, `params: ModelParams`, `metadata: dict[str, Any]`); the service validates the envelope via Pydantic schemas; the service-layer orchestrator looks up the logical model in the registry, calls the backend adapter with the resolved tag and merged sampling parameters, and returns a buffered JSON response shaped by the service's owned response schema. The path covers only the happy case — load-related concerns (semaphore, timeouts, backpressure errors) live in LIP-E004, lifecycle concerns (startup warm-up, idle shutdown) live in LIP-E005.

## Rationale

This epic is the project's reason for existing — without it, no inference happens and no consumer can integrate. It maps directly to G1 (consumer projects decoupled from the inference backend, by owning the contract here rather than borrowing Ollama's API surface), G3 (single observability point — the architectural placement where future tracing and logging will sit, even if implementation is out of v1 scope), and G4 (envelope absorbs future per-project controls, by establishing the `metadata` pass-through on day one). It is separate from the registry (LIP-E002) and the adapter (LIP-E003) because it is the orchestration layer that calls them — a distinct unit with its own user-visible behavior and its own tests.

## Boundary

In scope: the request and response Pydantic schemas; the FastAPI router endpoint that accepts the envelope; the service-layer orchestrator that wires registry-lookup → adapter-call → response; the happy-path return of a buffered JSON response shaped by the service-owned response schema. Out of scope: the model registry's data structure and lookup logic (LIP-E002); the Ollama HTTP client and request-response translation (LIP-E003); the QoS behavior under load including semaphore, bounded waiter count, timeouts, and structured error responses (LIP-E004); startup warm-up and idle shutdown (LIP-E005); state-inspection endpoints (LIP-E006); README and OpenAPI documentation surface (LIP-E007).

## Open questions

*This list is not exhaustive. Additional questions may surface during feature elicitation.*

- The exact endpoint path (`/v1/chat`, `/v1/complete`, `/inference`, etc.) and HTTP verb pattern have not been chosen. Likely follows OpenAI-compatible conventions for familiarity, but the project does not require OpenAI compatibility.
- The exact shape of the `Message` value-object (role + content fields, support for multipart content for multimodal inputs) requires resolution during feature thickening.
- Whether the response includes any metadata beyond the model output (timing, model used, request id) is undecided in v1.
