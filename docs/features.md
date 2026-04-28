# Features Catalog

Every capability in the LIP scaffold post-bootstrap, with a short description.

The features documented below describe what exists *right now* — the slim backend
skeleton inherited from the project template. The Local Inference Provider feature
itself will be scaffolded during feature-dev. See [graphs/LIP/](../graphs/LIP/) for
the planned feature tree.

`★ Insight ─────────────────────────────────────`
This file is a flat, discoverable index of what already exists — useful both for humans
onboarding and for AI agents deciding whether to reuse vs. build. It deliberately avoids
how-tos; it answers "what's in the box" only.
`─────────────────────────────────────────────────`

---

## Backend — Core Infrastructure

### Typed Settings ([app/core/config.py](../apps/backend/app/core/config.py))
Pydantic-settings based configuration. Three fields: `app_env`, `log_level`, and
`ollama_host` (defaulting to `http://localhost:11434`). LIP-specific settings (queue
depth, per-request timeout, idle-shutdown interval) will be added during feature-dev.

### Structured Logging ([app/core/logging.py](../apps/backend/app/core/logging.py))
Structlog pipeline with contextvar merging, ISO timestamps, and JSON output in production
/ console output in dev. Noisy loggers are silenced at WARNING.

### Request ID Middleware ([app/api/middleware.py](../apps/backend/app/api/middleware.py))
Validates incoming `X-Request-ID` headers against a UUID regex, generates a fresh UUID4
if missing or malformed, and binds it into structlog contextvars so every log line in
the request scope is correlatable. The ID is echoed back in the response header and
injected into every error body. This is the only middleware in v1.

### Health Endpoint ([app/api/health_router.py](../apps/backend/app/api/health_router.py))
`GET /health` is a pure liveness probe returning `{"status":"ok"}`. Readiness gating on
the warm-up signal will be added by LIP-E006-F001.

### Ollama launchd agent ([infra/launchd/com.lip.ollama.plist](../infra/launchd/com.lip.ollama.plist))
User-scope `launchd` agent that keeps the Ollama daemon running with LIP's calibrated
env vars (`OLLAMA_KEEP_ALIVE=300s`, `OLLAMA_NUM_PARALLEL=1`,
`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`).
Operator commands: `task ollama:install`, `task ollama:uninstall`, `task ollama:status`,
and `task check:plist` (validates with `plutil -lint`; also wired into `task check`).
Tests: [tests/unit/launchd/test_ollama_plist.py](../apps/backend/tests/unit/launchd/test_ollama_plist.py)
parses the plist with `plistlib` and asserts the env vars, binary path, and log paths.
See [docs/ollama-launchd.md](ollama-launchd.md) for env-var rationale and
customization for non-Homebrew installs.

---

## Backend — Error System

### DomainError Hierarchy ([app/exceptions/base.py](../apps/backend/app/exceptions/base.py))
Single `DomainError` base class carrying a `code: ClassVar[str]` and
`http_status: ClassVar[int]`, plus an optional typed Pydantic `params` model. Only the
code is stored in `args` so PII in params never accidentally ends up in stack traces.

### Generated Error Classes ([app/exceptions/_generated/](../apps/backend/app/exceptions/_generated/))
Every error code in `errors.yaml` is code-generated into its own Python file with a typed
params model (where applicable), enforcing the one-class-per-file rule. A `_registry.py`
maps error code strings back to classes for handler lookup. Current codes: `NOT_FOUND`,
`CONFLICT`, `VALIDATION_FAILED`, `INTERNAL_ERROR`, `RATE_LIMITED`. LIP-specific codes
(`QUEUE_FULL`, `INFERENCE_TIMEOUT`, `ADAPTER_CONNECTION`, `REGISTRY_NOT_FOUND`) will be
added during feature-dev.

### Exception Handlers ([app/api/errors.py](../apps/backend/app/api/errors.py))
Three handlers serialize `DomainError`, `RequestValidationError`, and unhandled
`Exception` into the same `{error: {code, params, details, request_id}}` envelope. This
guarantees every error the client sees is shape-identical regardless of where it
originated.

> **Forward-looking note:** LIP-E004-F004 will replace this envelope with
> `application/problem+json` (RFC 7807) when feature-dev for that feature lands.

### Error Contracts Package ([packages/error-contracts/](../packages/error-contracts/))
Single source of truth: `errors.yaml` drives a Python codegen step (classes + registry).
Adding an error is one yaml edit + `task errors:generate`. The `task check:errors`
target verifies committed generated files match the YAML.

---

## Backend — Shared Schemas

### Error Response Schemas ([app/schemas/](../apps/backend/app/schemas/))
`ErrorDetail`, `ErrorBody`, and `ErrorResponse` split across three files (one class each)
to satisfy the sacred one-class-per-file rule. Used for OpenAPI documentation; runtime
error bodies are constructed by the exception handlers directly.

---

## Backend — Architecture Enforcement

### Import-Linter Contracts ([apps/backend/architecture/import-linter-contracts.ini](../apps/backend/architecture/import-linter-contracts.ini))
Three forbidden contracts that work even before the LIP feature is scaffolded:
`app.core` cannot import from `app.features`, `app.exceptions` cannot import from
`app.features`, `app.schemas` cannot import from `app.features`. Feature-internal
layering (router -> service -> repository -> model) and feature-isolation contracts are
added during feature-dev.

---

## Backend — Tests

### Unit Tests ([apps/backend/tests/unit/](../apps/backend/tests/unit/))
Run in well under 10 seconds. Cover:

- **`tests/unit/core/`** — `test_config.py`: pydantic-settings parsing.
- **`tests/unit/exceptions/`** — `test_domain_errors.py` (DomainError construction)
  and `test_error_handler.py` (exception-handler serialization shape).
- **`tests/unit/features/inference/`** — value-object and schema unit tests:
  `test_message.py`, `test_model_params.py`, `test_content_part.py`,
  `test_text_content.py`, `test_image_content.py`, `test_audio_content.py`,
  `test_inference_request.py`, `test_inference_response.py`,
  `test_response_metadata.py`, `test_openapi_shape.py`, plus
  `repository/test_ollama_client.py` for the typed httpx client wrapper.
- **`tests/unit/launchd/`** — `test_ollama_plist.py` parses
  `infra/launchd/com.lip.ollama.plist` with `plistlib` and asserts the five
  Ollama env vars + binary path + log paths.

### Integration Tests ([apps/backend/tests/integration/](../apps/backend/tests/integration/))
httpx.AsyncClient via ASGITransport against the FastAPI app in-process. No DB, no
Testcontainers. Covers:

- `test_health.py` — `/health` liveness and request-ID middleware echo.
- `features/inference/test_lifecycle.py` — startup/shutdown lifespan against
  Ollama via `httpx.MockTransport` (no network).

### Contract Tests ([apps/backend/tests/contract/](../apps/backend/tests/contract/))
`test_schemathesis.py` is currently a sanity check that validates the generated
OpenAPI spec shape. A full Schemathesis fuzz against every endpoint will be wired
once the LIP feature router (LIP-E001-F002) lands and there are inference
operations to fuzz.

---

## CI/CD

### CI Workflow ([.github/workflows/ci.yml](../.github/workflows/ci.yml))
Two jobs: `backend-checks` (ruff + pyright + import-linter + pytest unit/integration/
contract) and `error-contracts` (Python codegen + tests + diff verification). Both are
hard gates on the `main-protection` ruleset.

### Dependabot ([.github/dependabot.yml](../.github/dependabot.yml))
Three ecosystems: `pip` for `apps/backend`, `pip` for `packages/error-contracts`, and
`github-actions`. Groups batch interlocking package updates atomically.

### Auto-merge & Lockfile-sync workflows
[.github/workflows/dependabot-automerge.yml](../.github/workflows/dependabot-automerge.yml)
auto-merges Dependabot PRs that pass all required checks.
[.github/workflows/dependabot-lockfile-sync.yml](../.github/workflows/dependabot-lockfile-sync.yml)
auto-fixes uv lockfile-gap on Dependabot PRs once the relevant variable + PAT are
configured. See [docs/automerge.md](automerge.md) for the full architecture.

---

## Tooling

### Taskfile ([Taskfile.yml](../Taskfile.yml))
Single orchestration entry point with `dev`, `check` (lint -> types -> arch -> test ->
errors), all test levels, ruff lint/format, errors generation/check.

### Pre-commit Hooks ([.pre-commit-config.yaml](../.pre-commit-config.yaml))
Pre-commit: whitespace/EOF/yaml/json/large-file checks + ruff fix + ruff format.
Pre-push: pytest unit.

### Editor & VCS Config
LF line endings, 4-space Python, generated files marked `linguist-generated`, pinned
tool versions for Python via `.tool-versions`.
