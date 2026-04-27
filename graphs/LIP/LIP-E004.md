---
type: epic
id: LIP-E004
parent: LIP
title: Backpressure, Timeouts & Error Responses
status: partially-detailed
priority: 40
dependencies: [LIP-E001]
---

## Short description

The QoS behavior of the inference pipeline under load: serial execution via `asyncio.Semaphore(1)`, bounded waiter count with HTTP 503, per-request timeout with HTTP 504, and the DomainError hierarchy producing structured error responses for every failure mode.

## Description

This epic delivers everything between "the happy path works" and "the service survives realistic load without crashing or hanging." Inference calls are gated by an `asyncio.Semaphore(1)` so only one inference executes at a time regardless of HTTP-level concurrency. A bounded waiter count (4 waiters per the provisional Quality Attributes setting) is enforced; the 5th waiter receives an HTTP 503 with a structured "queue full" DomainError. Each inference call is wrapped in `asyncio.wait_for` with a 180-second timeout; on expiry, the consumer receives an HTTP 504 with a structured "inference timeout" DomainError. All other failure modes — adapter connection errors, validation errors, registry-lookup misses — also surface through the DomainError hierarchy, producing predictable, contract-documented error response shapes that consumer projects can program against.

## Rationale

This epic implements G5 (reliability under known load) directly — without it, the service would either crash under burst load or hang requests beyond useful latency. It also implements the structured-error half of G3 — DomainError-shaped responses are the consumer-visible part of the observability story, even before structured logging is added in a later milestone. It is separate from the inference happy path (LIP-E001) because the QoS behavior has its own user-visible acceptance criteria (a 5th concurrent request returns 503 with a specific error shape; a request running longer than 180 s returns 504; a connection failure returns a specific error code) — distinct enough to justify their own epic and their own test suite.

## Boundary

In scope: the `asyncio.Semaphore(1)` wrapper; the bounded waiter-count enforcement that returns 503 when exceeded; the per-request `asyncio.wait_for` timeout with 504 response; the DomainError class hierarchy (queue-full, inference-timeout, adapter-connection-failure, validation-error, registry-not-found, etc.); the FastAPI exception handler that maps DomainError instances into structured JSON error responses with appropriate HTTP status codes. Out of scope: the happy-path orchestration the QoS layer wraps (LIP-E001); the state-inspection endpoints that report queue depth and timeout state (LIP-E006); structured-log emission of error events (out of v1 scope entirely).

## Open questions

*This list is not exhaustive. Additional questions may surface during feature elicitation.*

- The exact structured error response schema (fields, naming conventions, whether to follow RFC 7807 `application/problem+json` or a simpler service-owned shape) requires resolution during feature thickening.
- Whether the bounded waiter count and per-request timeout are configurable via `pydantic-settings` or hardcoded at 4 and 180 s in v1 needs a decision; configurable is closer to the CLAUDE.md pattern.
