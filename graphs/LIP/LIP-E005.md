---
type: epic
id: LIP-E005
parent: LIP
title: Lifecycle Management
status: not-started
priority: 50
dependencies: [LIP-E001]
---

## Short description

How the service starts (with a warm-up dummy inference before signalling ready), self-shuts after 10 minutes of idle, and how the Ollama daemon is configured via `launchd`.

## Description

This epic delivers the project's on-demand lifecycle posture. On startup, the FastAPI service performs a single dummy inference (e.g., one-token-in, one-token-out via the registry's default model) to ensure Ollama has loaded the model into memory before the service signals ready via `/health`. The service runs an internal idle timer that exits the process cleanly after 10 minutes with no inference traffic. Separately, the Ollama daemon is configured to run as a `launchd`-managed always-on service with `OLLAMA_KEEP_ALIVE=300s`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_FLASH_ATTENTION=1`, and `OLLAMA_KV_CACHE_TYPE=q8_0` — the daemon is the system-managed piece, while the FastAPI service is the on-demand piece launched by consumers when needed. Per the resolution of the wake-up mechanism question, the FastAPI service does *not* ship its own wake-up wrapper script; consumers are responsible for launching the process and polling `/health`.

## Rationale

This epic implements G6 (on-demand lifecycle) directly, and supports G5 (reliability) by ensuring the model is loaded before serving real requests, eliminating cold-load pauses on the first inference call. It is separate from the inference path (LIP-E001) and the operational visibility surface (LIP-E006) because it is fundamentally a startup-and-shutdown concern with its own sequencing requirements (warm-up must complete before `/health` returns ready) and its own external artifact (the Ollama `launchd` plist, which is configuration, not Python code).

## Boundary

In scope: the FastAPI startup hook performing the warm-up dummy inference; the idle-shutdown timer exiting the process cleanly after 10 minutes of no inference traffic; the Ollama `launchd` plist file with the documented env vars; the plist's installation procedure. Out of scope: the inference path the warm-up uses (LIP-E001); the `/health` endpoint that reports the warm-up's completion (LIP-E006); a wake-up wrapper script (rejected — consumer-side responsibility); auto-start of the FastAPI service at Mac boot (rejected — contradicts G6).

## Open questions

*This list is not exhaustive. Additional questions may surface during feature elicitation.*

- The exact mechanism for the idle-shutdown timer — a background task using `asyncio.sleep` and a request-counter, vs a per-request reset of an idle timestamp checked by a watchdog — requires a design decision during thickening.
- Whether the warm-up dummy inference uses the actual `default-fast` model or a fixed minimal prompt is undecided.
- The exact location of the Ollama `launchd` plist within the repo (`infra/launchd/`, `apps/backend/launchd/`, etc.) needs to fit existing template conventions.
