---
type: epic
id: LIP-E002
parent: LIP
title: Model Registry
status: not-started
priority: 20
dependencies: []
---

## Short description

An in-process metadata table that maps logical model names to backend tags and centralizes per-model sampling defaults, capability flags, and context-window maxima.

## Description

This epic delivers the registry mechanism that lets consumers reference models by stable logical names (e.g., `"default-fast"`) while the service handles the mapping to backend-specific tags (e.g., `"gemma4:e2b"` today, possibly `"gemma4-e2b-mlx"` post-backend-swap). The registry is also the single home for per-model knowledge: the recommended sampling defaults applied when the consumer's `params` does not override them, the capability flags (text/image/audio support) the service uses to validate incoming envelopes, and the context-window maximum that bounds prompt length. The registry is an in-process data structure populated at startup; v1 ships exactly one registry entry (Gemma 4 E2B); future entries are added by editing code, not by runtime configuration.

## Rationale

This epic implements the mechanism behind two project goals: G1 (consumer projects decoupled from the inference backend — the logical-name-to-tag layer is the core decoupling mechanism; consumers never see backend-specific identifiers) and G2 (per-model knowledge in the service — the registry is the single home for sampling defaults and model metadata, so consumer projects do not duplicate or drift on Gemma-specific facts). It is separate from the inference orchestrator (LIP-E001) and the backend adapter (LIP-E003) because the registry is conceptually a data layer that both consume — reusable, testable in isolation, and would survive even if the service's transport changed.

## Boundary

In scope: the in-process registry data structure; the initial Gemma 4 E2B entry with its sampling defaults, capability flags (text + image + audio), and 128 K context-window maximum; the lookup-by-logical-name operation; the merge logic that applies per-model defaults under consumer-supplied overrides; the capability-flag exposure that the orchestrator can query. Out of scope: the request/response schemas the registry's outputs flow into (LIP-E001); the adapter that takes the resolved tag and calls Ollama (LIP-E003); runtime registry editing — registry changes are code changes in v1.

## Open questions

*This list is not exhaustive. Additional questions may surface during feature elicitation.*

- The exact schema of a registry entry (what fields beyond logical name, backend tag, sampling defaults, capability flags, context max) is to be resolved during feature thickening.
- Whether logical names are namespaced (e.g., `"text/default-fast"`) or flat (e.g., `"default-fast"`) is undecided.
- The initial sampling defaults for Gemma 4 E2B (temperature, top_p, top_k) need concrete values, ideally informed by the brief's pre-elicitation homework.
