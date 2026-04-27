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

- **What:** A lightweight spec-shape test as a canary for "did the OpenAPI even
  generate." A full Schemathesis fuzz against every endpoint will be wired once the
  LIP feature router (LIP-E001-F002) lands and there are inference operations to fuzz.
- **Location:** `tests/contract/test_schemathesis.py`.

## Type-Driven Discipline

- Pyright strict. Enforced in CI. Type error = build failure.

## Test Naming

| Context | Pattern | Example |
|---|---|---|
| Python | `test_<unit>_<scenario>_<expected>` | `test_inference_service_returns_response_for_valid_envelope` |

## Test File Location

- Unit: `tests/unit/<mirrors source tree>/test_<module>.py`
- Integration: `tests/integration/<mirrors source tree>/test_<module>.py`
- Contract: `tests/contract/test_schemathesis.py`

## Pre-commit / Pre-push / CI

| Layer | What runs | Speed |
|---|---|---|
| Pre-commit | ruff, trailing-whitespace, yaml/json check | ~5-10s |
| Pre-push | pytest unit | ~5-15s |
| CI | All three test levels + type checker + import-linter + error-contracts regen check | Full |

## Explicitly Excluded

- Property-based testing (Hypothesis)
- Performance / load testing (Locust, k6)
- Mutation testing (mutmut)
- Snapshot testing (forbidden — snapshots rot)
- Fuzz testing beyond Schemathesis
