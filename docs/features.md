# Features Catalog

Every capability in the LIP scaffold, with a short description.

The features documented below describe what exists *right now*. Five LIP feature
nodes have already landed in code: LIP-E001-F001 inference envelopes, LIP-E003-F001
lifespan OllamaClient, LIP-E003-F002 envelope↔Ollama translation, LIP-E004-F004
RFC 7807 problem+json, and LIP-E005-F003 Ollama launchd agent. Of those, three
carry `status: implemented` in [graphs/LIP/](../graphs/LIP/) (E001-F001, E003-F001,
E005-F003); the other two carry `status: verifiable`. `service/` and `router/`
arrive with LIP-E001-F002 per ADR-011 lazy scaffolding.

`★ Insight ─────────────────────────────────────`
This file is a flat, discoverable index of what already exists — useful both for humans
onboarding and for AI agents deciding whether to reuse vs. build. It deliberately avoids
how-tos; it answers "what's in the box" only.
`─────────────────────────────────────────────────`

---

## Backend — Core Infrastructure

### Typed Settings ([app/core/config.py](../apps/backend/app/core/config.py))
Pydantic-settings based configuration. Seven fields: `app_env`, `log_level`,
`ollama_host` (defaulting to `http://localhost:11434`), `bind_host` /
`bind_port` (uvicorn binding, validated to reject `0.0.0.0` unless
`allow_public_bind=true`), `allow_public_bind` (escape hatch for the
public-bind clamp), and `allow_external_ollama` (escape hatch for the
SSRF-clamp validator that otherwise restricts the Ollama host to loopback /
RFC1918 / link-local). Every field reads from a `LIP_`-prefixed env var
(e.g. `LIP_OLLAMA_HOST`) — set via `env_prefix` on the SettingsConfigDict —
so a single shell can run both the Ollama daemon (which reads `OLLAMA_HOST`)
and LIP without crossed wires. LIP-specific settings (queue depth,
per-request timeout, idle-shutdown interval) will be added during feature-dev.

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

### Ollama Launchd Agent ([infra/launchd/com.lip.ollama.plist](../infra/launchd/com.lip.ollama.plist))
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
`CONFLICT`, `VALIDATION_FAILED`, `INTERNAL_ERROR`, `RATE_LIMITED`, `QUEUE_FULL`,
`INFERENCE_TIMEOUT`, `ADAPTER_CONNECTION_FAILURE`, `REGISTRY_NOT_FOUND`,
`MODEL_CAPABILITY_NOT_SUPPORTED`. (Note: `ADAPTER_CONNECTION_FAILURE` is the actual
code; earlier drafts of this doc abbreviated it.)

### Exception Handlers ([app/api/errors.py](../apps/backend/app/api/errors.py))
Four handlers serialize `DomainError`, `RequestValidationError`, `StarletteHTTPException`,
and unhandled `Exception` into a unified RFC 7807 `application/problem+json`
ProblemDetails envelope (per LIP-E004-F004, PR #14). Every error the client sees is
shape-identical regardless of where it originated.

### Error Contracts Package ([packages/error-contracts/](../packages/error-contracts/))
Single source of truth: `errors.yaml` drives a Python codegen step (classes + registry).
Adding an error is one yaml edit + `task errors:generate`. The `task check:errors`
target verifies committed generated files match the YAML.

---

## Backend — Shared Schemas

### Error Response Schemas ([app/schemas/](../apps/backend/app/schemas/))
`ProblemDetails`, `ProblemExtras`, `ValidationErrorDetail`, and `HealthResponse` split
across four files (one class each) to satisfy the sacred one-class-per-file rule.
`ProblemDetails` implements RFC 7807 problem+json; `ProblemExtras` is the typed
extension-key container; `ValidationErrorDetail` is the per-field shape inside
validation problem+json; `HealthResponse` is the liveness payload.

---

## Backend — Architecture Enforcement

### Import-Linter Contracts ([apps/backend/architecture/import-linter-contracts.ini](../apps/backend/architecture/import-linter-contracts.ini))
Thirteen contracts protect the layer boundaries:

- `core-no-features`, `exceptions-no-features`, `schemas-no-features` — the three
  cross-cutting layers cannot reach into any feature.
- `core-is-leaf`, `exceptions-is-leaf`, `schemas-is-leaf` — none of the three
  cross-cutting layers may reach into the others either; layering stays acyclic.
- `no-direct-generated-error-imports` — only `app.exceptions/__init__` may
  import from `app.exceptions._generated`; everything else uses the public
  re-exports per CLAUDE.md.
- `api-errors-feature-agnostic` — the api-error layer cannot reach into any
  feature, keeping the RFC 7807 envelope decoupled from inference specifics.
- `features-are-independent` — features cannot import each other (no-op while
  only one feature exists; one-line edit when the second lands).
- `inference-model-no-schemas`, `inference-repository-no-schemas`,
  `inference-model-no-repository`, `inference-schemas-no-repository` — within
  the inference slice, lower layers cannot reach into wire schemas, and
  `model/` is the bottom of the layering. The full router → service →
  repository → model layering is added per-layer as the feature router and
  service land.

---

## Backend — Tests

### Unit Tests ([apps/backend/tests/unit/](../apps/backend/tests/unit/))
Run in well under 10 seconds. Cover:

- **`tests/unit/core/`** — `test_config.py`: pydantic-settings parsing + clamps.
- **`tests/unit/exceptions/`** — `test_base.py` (DomainError ergonomics),
  `test_domain_errors.py` (per-code construction), `test_registry.py`
  (`ERROR_CLASSES` lookup invariants), `test_error_handler.py` (exception-handler
  unit tests; mirrors `app/api/errors.py`).
- **`tests/unit/schemas/`** — `test_problem_details.py`, `test_validation_error_detail.py`
  for the RFC 7807 wire shapes.
- **`tests/unit/features/inference/`** — value-object and schema unit tests:
  `test_message.py`, `test_model_params.py`, `test_content_part.py`,
  `test_text_content.py`, `test_image_content.py`, `test_audio_content.py`,
  `test_inference_request.py`, `test_inference_response.py`,
  `test_response_metadata.py`, `test_ollama_chat_result.py`,
  `test_openapi_shape.py`, plus `repository/test_ollama_client.py` and
  `repository/test_ollama_translation.py` for the typed httpx client wrapper
  and envelope↔Ollama translation.
- **`tests/unit/launchd/`** — `test_ollama_plist.py` parses
  `infra/launchd/com.lip.ollama.plist` with `plistlib` and asserts the five
  Ollama env vars + binary path + log paths.

### Integration Tests ([apps/backend/tests/integration/](../apps/backend/tests/integration/))
httpx.AsyncClient via ASGITransport against the FastAPI app in-process. No DB, no
Testcontainers. Covers:

- `api/test_health.py` — `/health` liveness and request-ID middleware echo.
- `test_problem_details.py` — RFC 7807 problem+json envelope shapes through the
  registered handlers (DomainError, RequestValidationError, StarletteHTTPException,
  generic Exception).
- `features/inference/test_lifecycle.py` — startup/shutdown lifespan against
  Ollama via `httpx.MockTransport` (no network).
- `features/inference/test_chat.py` — `OllamaClient.chat()` against
  `httpx.MockTransport` covering happy path, error mapping, body-shape invariants.
- `test_app_factory.py` — `create_app` switches OpenAPI exposure on `LIP_APP_ENV`.

### Contract Tests ([apps/backend/tests/contract/](../apps/backend/tests/contract/))
`test_openapi_shape.py` validates the generated OpenAPI spec shape (one canary
test that runs before any fuzz attempts to load it).
`test_problem_details_contract.py` covers the LIP-E004-F004 RFC 7807 wire shape
(ProblemDetails as a published component, RFC 7807 fields + LIP extensions
present, `application/problem+json` advertised on the `/health` default
response). A full Schemathesis fuzz against every endpoint will be wired once
the LIP feature router (LIP-E001-F002) lands and there are inference operations
to fuzz.

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
Single orchestration entry point with `dev`, `check` (lint, format, types, architecture,
tests, error contracts, plist, lockfile), all test levels, ruff lint/format, errors
generation/check, plus on-demand `check:audit` (pip-audit) and `check:coverage`
(90% gate).

### Pre-commit Hooks ([.pre-commit-config.yaml](../.pre-commit-config.yaml))
Pre-commit: whitespace/EOF/yaml/json/large-file checks + ruff fix + ruff format.
Pre-push: pytest unit.

### Editor & VCS Config
LF line endings, 4-space Python, generated files marked `linguist-generated`, pinned
tool versions for Python via `.tool-versions`.
