---
type: epic
id: LIP-E005
parent: LIP
title: Lifecycle Management
status: fully-detailed
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

None. All three Epic-level questions raised at requirements-elicitation time were resolved during feature thickening:

- **Idle-shutdown timer mechanism** — resolved by F002: a polling background watchdog (`async def idle_watchdog`) that sleeps 60 s per iteration, checks `time.monotonic() - tracker.last_finish() >= idle_seconds`, and skips when `waiter_counter.current() > 0`. Simpler than per-request-reset + remaining-time-recompute; granularity (60 s on a 600 s default) is acceptable. `LastRequestTracker.record()` is called at both entry and `finally` of `InferenceService.run()` so all paths through the orchestrator update the timer.
- **Warm-up dummy inference body** — resolved by F001: real registry-resolved path. Calls `client.chat()` with the `default-task` registry entry, `Message(role="user", content="ok")`, `ModelParams(max_tokens=1)`. Exercises the full registry → backend-tag resolution at startup, catching mis-wirings before the first user request. Bypasses the orchestrator's QoS layer (no semaphore/counter pollution).
- **launchd plist location** — resolved by F003: `infra/launchd/com.lip.ollama.plist` with `docs/ollama-launchd.md` documenting install/uninstall/customize procedures. Validated by `plutil -lint` in `task check`. Plist installed to `~/Library/LaunchAgents/com.lip.ollama.plist` and bootstrapped via `launchctl bootstrap gui/$(id -u) …`.
