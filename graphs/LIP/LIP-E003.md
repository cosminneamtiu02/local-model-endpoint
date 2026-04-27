---
type: epic
id: LIP-E003
parent: LIP
title: Ollama Backend Adapter
status: not-started
priority: 30
dependencies: []
---

## Short description

The `httpx` async client that wraps Ollama's HTTP API, configurable via `pydantic-settings`, and translates the service's envelope to Ollama-specific calls and back.

## Description

This epic delivers the seam at which all Ollama-specific knowledge is concentrated. The adapter holds an `httpx.AsyncClient` configured with `OLLAMA_HOST` (a `pydantic-settings` field defaulting to `http://localhost:11434`), translates an outgoing service request — a model tag plus a `Message` list plus merged sampling parameters — into Ollama's expected request format, and translates Ollama's response back into the service's owned response schema. Connection failures, malformed responses, and unexpected error shapes from Ollama are mapped into service-internal `DomainError` types so callers above the adapter never see Ollama-specific exceptions. When G1 fires (the future backend swap), the adapter is the unit replaced; nothing above it should change.

## Rationale

This epic is the strongest expression of G1 (consumer projects decoupled from the inference backend). Without a clean adapter seam, backend-specific calls would scatter through the orchestrator and force a multi-file rewrite at swap time. With it, swapping Ollama for vLLM or MLX or a hosted provider replaces only this epic's code. It is separate from the orchestrator (LIP-E001) and the registry (LIP-E002) because it is a thin translation layer with its own dependencies (`httpx`), its own configuration surface (Ollama host), and its own failure modes (connection errors, Ollama API changes).

## Boundary

In scope: the configurable Ollama host via `pydantic-settings`; the `httpx.AsyncClient` setup; the request translation from the service envelope (with the registry-resolved tag) into Ollama's API format; the response translation from Ollama's format into the service's owned response schema; the mapping of Ollama-specific failures (connection refused, HTTP non-2xx, malformed JSON) into `DomainError` instances. Out of scope: the registry that supplies the resolved tag (LIP-E002); the orchestrator that decides when to call (LIP-E001); the timeout that wraps the call (LIP-E004's `asyncio.wait_for`); the warm-up dummy inference that uses the adapter on startup (LIP-E005).

## Open questions

*This list is not exhaustive. Additional questions may surface during feature elicitation.*

- Whether the adapter exposes a single high-level `chat()` method or multiple methods (one per Ollama endpoint family — `/api/chat`, `/api/generate`, `/api/embeddings`) is to be resolved during feature thickening.
- Connection-pool sizing and `httpx` transport-layer timeout (separate from LIP-E004's per-request timeout) will need a default value.
