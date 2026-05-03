# Testing

## Philosophy

This is a test-driven development project. Every piece of functionality is written
test-first: red -> green -> refactor. New code without a test is a bug.

## Three Test Levels

All three levels are mandatory for every feature. Missing a level = incomplete work.
A fourth level — e2e against a running Ollama — will be added when the LIP feature
router lands and there is end-to-end behavior worth covering against the real backend.

### 1. Unit Tests

- **What:** Individual functions, classes, pure logic in isolation.
- **Dependencies:** None. No network, no file system.
- **Tooling:** pytest + pytest-asyncio.
- **Location:** `tests/unit/` mirroring source tree.
- **Speed budget:** Entire unit suite < 10 seconds locally.

### 2. Integration Tests

- **What:** FastAPI app exercised in-process via `httpx.ASGITransport`. The full request
  pipeline runs (middleware, exception handler, routes, schemas) but no external network
  is touched.
- **Tooling:** pytest + httpx.AsyncClient + ASGITransport.
- **Location:** `tests/integration/`.
- **Speed budget:** Entire integration suite < 30 seconds locally.
- **No database.** LIP holds no persistent state. No Testcontainers.

### 3. Contract Tests

- **What:** Spec-shape canary for "did the OpenAPI even generate" plus the LIP-E004-F004
  RFC 7807 wire-shape contract (ProblemDetails as a published component, RFC 7807 fields
  + LIP extensions present, `application/problem+json` advertised on the `/health` default
  response). A full Schemathesis fuzz against every endpoint will be wired once the LIP
  feature router (LIP-E001-F002) lands and there are inference operations to fuzz.
- **Location:** `tests/contract/test_openapi_shape.py` (canary), `tests/contract/test_problem_details_contract.py` (RFC 7807).

## Lifecycle and lifespan integration

The canonical pattern for testing FastAPI lifespan code (startup warm-up,
shutdown timer, etc.) against Ollama without hitting the network is
`httpx.MockTransport` injected directly into an `OllamaClient` constructor
inside each test (NOT through the integration `conftest.py`'s shared ASGI
client — that fixture targets `app.main.app`, which uses the production
lifespan). See [tests/integration/features/inference/test_lifecycle.py](../apps/backend/tests/integration/features/inference/test_lifecycle.py)
for the working example: the test builds its own `OllamaClient(...,
transport=httpx.MockTransport(...))`, drives it through `__aenter__` /
`chat` / `__aexit__`, and asserts on the orchestration shape (request
order, payload, error mapping) without any real Ollama process running.

## Type-Driven Discipline

- Pyright strict. Enforced in CI. Type error = build failure.

## Test Naming

| Context | Pattern | Example |
|---|---|---|
| Python | `test_<unit>_<scenario>_<expected>` | `test_inference_service_returns_response_for_valid_envelope` |

## Test File Location

- Unit: `tests/unit/<mirrors source tree>/test_<module>.py`
- Integration: `tests/integration/<mirrors source tree>/test_<module>.py`
- Contract: `tests/contract/test_openapi_shape.py` (OpenAPI canary), `tests/contract/test_problem_details_contract.py` (RFC 7807 wire shape).

## Pre-commit / Pre-push / CI

| Layer | What runs | Speed |
|---|---|---|
| Pre-commit | ruff (lint + format), trailing-whitespace, end-of-file-fixer, check-yaml/json, large-file guard, detect-secrets, Taskfile syntax check (per ADR-009) | ~5-10s |
| Pre-push | pytest unit + pyright + import-linter (per ADR-009) | ~30-60s |
| CI | All three test levels + type checker + import-linter + error-contracts regen check | Full |

## Explicitly Excluded

- Property-based testing (Hypothesis)
- Performance / load testing (Locust, k6)
- Mutation testing (mutmut)
- Snapshot testing (forbidden — snapshots rot)
- Fuzz testing beyond Schemathesis
