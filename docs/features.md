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
`ollama_host: AnyHttpUrl` (default `http://localhost:11434`), `bind_host` /
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

### Request ID Middleware ([app/api/request_id_middleware.py](../apps/backend/app/api/request_id_middleware.py))
Validates incoming `X-Request-ID` headers against a UUID regex, generates a fresh UUID4
if missing or malformed, and binds it into structlog contextvars so every log line in
the request scope is correlatable. The ID is echoed back in the response header and
injected into every error body. This is the only middleware in v1.

### Health Endpoint ([app/api/health_router.py](../apps/backend/app/api/health_router.py))
`GET /health` is a pure liveness probe returning `{"status":"ok"}`. Readiness gating on
the warm-up signal will be added by LIP-E006-F001.

### Ollama Launchd Agent ([infra/launchd/com.lip.ollama.plist.tmpl](../infra/launchd/com.lip.ollama.plist.tmpl))
User-scope `launchd` agent that keeps the Ollama daemon running with LIP's calibrated
env vars (`OLLAMA_KEEP_ALIVE=300s`, `OLLAMA_NUM_PARALLEL=1`,
`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`).
Operator commands: `task ollama:install`, `task ollama:uninstall`, `task ollama:status`,
and `task check:plist` (validates with `plutil -lint`; also wired into `task check`).
Tests: [tests/unit/infra/launchd/test_ollama_plist.py](../apps/backend/tests/unit/infra/launchd/test_ollama_plist.py)
parses the plist with `plistlib` and asserts the env vars, binary path, and log paths.
See [docs/ollama-launchd.md](ollama-launchd.md) for env-var rationale and
customization for non-Homebrew installs.

---

## Backend — Error System

### DomainError Hierarchy ([app/exceptions/base.py](../apps/backend/app/exceptions/base.py))
Single `DomainError` base class carrying five required ClassVars enforced by
`__init_subclass__`: `code: ClassVar[str]` (SCREAMING_SNAKE wire code),
`http_status: ClassVar[int]` (4xx/5xx status code), `type_uri: ClassVar[str]`
(`urn:lip:error:<code-kebab>` per RFC 7807 §3.1), `title: ClassVar[str]`
(short summary), and `detail_template: ClassVar[str]` (per-instance
str.format template). Plus an optional typed Pydantic `params` model. Only the
code is stored in `args` so PII in params never accidentally ends up in stack traces.

### Generated Error Classes ([app/exceptions/_generated/](../apps/backend/app/exceptions/_generated/))
Every error code in `errors.yaml` is code-generated into its own Python file with a typed
params model (where applicable), enforcing the one-class-per-file rule. A `_registry.py`
maps error code strings back to classes for handler lookup. The canonical list of codes
lives in [`packages/error-contracts/errors.yaml`](../packages/error-contracts/errors.yaml)
— do not duplicate it here (hand-curated lists drift the moment a code is added).

### Exception Handlers ([app/api/exception_handler_registry.py](../apps/backend/app/api/exception_handler_registry.py))
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
validation problem+json; `HealthResponse` is the liveness payload. A fifth file
`wire_constants` centralizes the UUID regex, request-id length, instance-path cap,
RFC 7807 about:blank type URI, X-Request-ID and Content-Language header
spellings, and the `application/problem+json` media-type / Content-Language
values reused across the request_id middleware, `ProblemDetails`,
`app.api.deps`, and the inference response envelope — see the module docstring
for the centralization rationale.

---

## Backend — Architecture Enforcement

### Import-Linter Contracts ([apps/backend/architecture/import-linter-contracts.ini](../apps/backend/architecture/import-linter-contracts.ini))
Fifteen contracts protect the layer boundaries:

- **1 generated-error gate** — `no-direct-generated-error-imports`: only
  `app.exceptions/__init__` may import from `app.exceptions._generated`;
  everything else uses the public re-exports per CLAUDE.md.
- **4 leaf rules** — `core-is-leaf`, `exceptions-is-leaf`, `schemas-is-leaf`,
  and `inference-model-is-leaf`: each layer is forbidden from importing
  any of the others, so layering stays acyclic. `inference-model-is-leaf`
  absorbs the model→repository forbidden edge that previously lived in a
  separate `inference-model-no-repository` contract.
- **1 cross-feature isolation** — `features-are-independent`: features cannot
  import each other (vacuously kept while only one feature exists; the
  next feature added must be appended to the contract's `modules =` list).
- **3 inference-internal layering** — `inference-model-no-schemas`,
  `inference-repository-no-schemas`, and `inference-schemas-no-repository`.
  Within the inference slice, lower layers cannot reach into wire schemas.
  The full router → service → repository → model layering is added
  per-layer as the feature router and service land.
- **2 inference cross-layer** — `inference-schemas-cross-layer` and
  `inference-repository-cross-layer`: the inference feature's `schemas/`
  cannot reach into `app.api`/`app.exceptions`, and `repository/` cannot
  reach into `app.api` or sibling `schemas/`. Defense-in-depth around the
  feature → cross-cutting-layer boundary.
- **4 api-cross-cutting** — `api-exception-handlers-feature-agnostic`,
  `api-request-id-middleware-feature-agnostic`,
  `api-health-router-feature-agnostic`, and
  `api-uses-inference-feature-root`: the global error path, request-id
  middleware, the health router (defense-in-depth that `/health` stays
  process-only and never grows a daemon-ping arm), and the api ↔
  inference boundary are all feature-agnostic (or feature-root-only) by
  contract, so a drift where a handler sniffs feature-specific shape
  is mechanically caught.

---

## Backend — Tests

### Unit Tests ([apps/backend/tests/unit/](../apps/backend/tests/unit/))
Run in well under 10 seconds. Cover:

- **`tests/unit/core/`** — `test_config.py` (pydantic-settings parsing + clamps),
  `test_logging.py` (structlog pipeline configuration).
- **`tests/unit/api/`** — `test_deps.py` (Settings factory + DI wiring),
  `test_exception_handler_registry.py` (DomainError → ProblemDetails serialization).
- **`tests/unit/exceptions/`** — `test_base.py` (DomainError ergonomics),
  `test_domain_errors.py` (per-code construction), `test_registry.py`
  (`ERROR_CLASSES` lookup invariants), plus `test_errors_yaml_drift_guard.py`,
  `test_params_frozen_drift_guard.py`, `test_problem_extras_drift_guard.py`,
  `test_screaming_snake_pattern_drift_guard.py`, and
  `test_handwritten_files_drift_guard.py` for codegen, ProblemExtras drift,
  SCREAMING_SNAKE pattern lockstep, and the "only base.py is hand-written"
  invariant under `app/exceptions/`.
- **`tests/unit/schemas/`** — `test_health_response.py`, `test_problem_details.py`,
  `test_problem_extras.py`, `test_validation_error_detail.py` (one test file per
  schema-package class).
- **`tests/unit/`** (top-level) — `test_filterwarnings_anyio_suppression.py`
  (self-test that the anyio.streams.memory ResourceWarning narrowing in
  `pyproject.toml`'s `filterwarnings` is still effective),
  `test_no_test_classes_guard.py` (sentinel asserting the
  `pytest_sessionstart` hook + python_classes regex catch a stray
  `class Test...` collection — sacred-rule "Never write a test class"),
  and `test_pytest_asyncio_config.py` (drift-guard pinning the
  `asyncio_default_fixture_loop_scope` /
  `asyncio_default_test_loop_scope` / `asyncio_mode` lockstep in
  `pyproject.toml`).
- **`tests/unit/features/inference/`** — mirrors `app/features/inference/`,
  plus `test_request_id_fixture_drift_guard.py` at the top level
  (pins the shared `VALID_REQUEST_ID` fixture used across the feature's
  unit + integration tests):
  - `model/` — `test_message.py`, `test_model_params.py`, `test_content_part.py`,
    `test_text_content.py`, `test_image_content.py`, `test_audio_content.py`,
    `test_ollama_chat_result.py`, `test_ollama_translation.py`,
    `test_value_objects_frozen_drift_guard.py` (mirror of
    `test_params_frozen_drift_guard.py` for the inference value-object
    family). The internal helpers `_validators.py`, `dos_caps.py`, and
    `finish_reason.py` are exercised transitively through these test files
    (no dedicated test files).
  - `schemas/` — `test_inference_request.py`, `test_inference_response.py`,
    `test_response_metadata.py`, `test_inference_schema_shapes.py`
  - `repository/` — `test_ollama_client.py` (typed httpx wrapper)
- **`tests/unit/infra/launchd/`** — `test_ollama_plist.py` parses
  `infra/launchd/com.lip.ollama.plist.tmpl` with `plistlib` and asserts the
  five Ollama env vars + binary path + log paths.

### Integration Tests ([apps/backend/tests/integration/](../apps/backend/tests/integration/))
httpx.AsyncClient via ASGITransport against the FastAPI app in-process. No DB, no
Testcontainers. Covers:

- `api/test_health_router.py` — `/health` liveness shape.
- `api/test_request_id_middleware.py` — request-ID propagation, header echo,
  contextvar binding, body-size DoS guard.
- `test_exception_handler_chain.py` — RFC 7807 problem+json envelope shapes through
  the registered handlers (DomainError, RequestValidationError, StarletteHTTPException,
  generic Exception).
- `features/inference/test_lifecycle.py` — startup/shutdown lifespan against
  Ollama via `httpx.MockTransport` (no network).
- `features/inference/test_chat.py` — `OllamaClient.chat()` against
  `httpx.MockTransport` covering happy path, error mapping, body-shape invariants.
- `test_main.py` — `create_app` switches OpenAPI exposure on `LIP_APP_ENV`.

### Contract Tests ([apps/backend/tests/contract/](../apps/backend/tests/contract/))
`test_openapi_shape.py` validates the generated OpenAPI spec shape (one canary
test that runs before any fuzz attempts to load it).
`test_problem_details_shape.py` covers the LIP-E004-F004 RFC 7807 wire shape
(ProblemDetails as a published component, RFC 7807 fields + LIP extensions
present, `application/problem+json` advertised on the `/health` default
response). A full Schemathesis fuzz against every endpoint will be wired once
the LIP feature router (LIP-E001-F002) lands and there are inference operations
to fuzz.

---

## CI/CD

### CI Workflow ([.github/workflows/ci.yml](../.github/workflows/ci.yml))
Three jobs: `backend-checks` (lockfile-freshness + ruff + pyright + import-linter +
pytest unit/integration/contract + coverage gate + pip-audit + secret scan),
`error-contracts` (Python codegen + tests + diff verification + lint/format/audit),
and `darwin-checks` (macOS-only `plutil` validation of the launchd plist template).
All three are hard gates on the `main-protection` ruleset.

### Dependabot ([.github/dependabot.yml](../.github/dependabot.yml))
Four update blocks: `pip` for `apps/backend`, `pip` for `packages/error-contracts`,
`github-actions`, and `pre-commit` (so `rev:` SHAs in `.pre-commit-config.yaml`
get bumped on the same Dependabot cadence). Groups batch interlocking package
updates atomically.

### Auto-merge & Lockfile-sync workflows
[.github/workflows/dependabot-automerge.yml](../.github/workflows/dependabot-automerge.yml)
auto-merges Dependabot PRs that pass all required checks.
[.github/workflows/dependabot-lockfile-sync.yml](../.github/workflows/dependabot-lockfile-sync.yml)
auto-fixes uv lockfile-gap on Dependabot PRs once the relevant variable + PAT are
configured. See [docs/automerge.md](automerge.md) for the full architecture.

---

## Tooling

### Taskfile ([Taskfile.yml](../Taskfile.yml))
Single orchestration entry point with `dev` and `check` (runs lint, format,
lockfile, types, architecture, coverage-gated tests, error contracts, plist,
audit, secrets — same gate CI runs). All test levels are also runnable
individually; ruff lint/format, errors generation/check, pip-audit, and
detect-secrets are exposed as standalone targets too.

### Pre-commit Hooks ([.pre-commit-config.yaml](../.pre-commit-config.yaml))
Pre-commit: detect-secrets, trailing-whitespace, end-of-file-fixer,
check-yaml/json, check-added-large-files, ruff (lint, no auto-fix) +
ruff-format, and a Taskfile-syntax local hook.
Pre-push: backend unit tests + error-contracts unit tests only (per
ADR-009 + lane 10.6; the slower pyright/import-linter/integration/
contract gates live in CI to avoid double-running and the `--no-verify`
pressure that double-running creates). Pre-commit/-push installed
together via `default_install_hook_types`.

### Editor & VCS Config
LF line endings, 4-space Python, generated files marked `linguist-generated`, pinned
tool versions for Python via `.tool-versions`.
