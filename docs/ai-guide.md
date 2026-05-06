# AI Guide — LIP Scaffold Overview

What is already implemented in the LIP project, what is not, and how the pieces connect.
Read `CLAUDE.md` for all rules and forbidden patterns. Read [docs/disambiguated-idea.md](disambiguated-idea.md)
for the full project specification and [graphs/LIP/](../graphs/LIP/) for the Project +
Epic + Feature tree.

## Backend — What's Built

**Core infrastructure** is in place: app factory ([apps/backend/app/main.py](../apps/backend/app/main.py)),
configuration via pydantic-settings ([app/core/config.py](../apps/backend/app/core/config.py)),
structured logging via structlog ([app/core/logging.py](../apps/backend/app/core/logging.py)),
and FastAPI dependency injection for settings ([app/api/deps.py](../apps/backend/app/api/deps.py)).

**Middleware** is reduced to request-id propagation plus a per-request access log
([app/api/request_id_middleware.py](../apps/backend/app/api/request_id_middleware.py)).
Security headers and CORS were stripped during project-bootstrap because the service is
local-network-only. The access log emits a single `request_completed` JSON line per
request (method, path, status, duration_ms, request_id, client addr); see
[docs/runbook.md](runbook.md) for the operator triage shape.

**Error handling** is fully implemented via the code-generated system. Error codes live
in [packages/error-contracts/errors.yaml](../packages/error-contracts/errors.yaml) — a
codegen script produces one Python exception class per error code in
`app/exceptions/_generated/`. Four handlers in
[app/api/exception_handler_registry.py](../apps/backend/app/api/exception_handler_registry.py) map `DomainError`,
`RequestValidationError`, `StarletteHTTPException`, and unhandled `Exception` into a
unified RFC 7807 `application/problem+json` ProblemDetails envelope (LIP-E004-F004).

**Health endpoint** is at root level (outside `/v1/`):
[app/api/health_router.py](../apps/backend/app/api/health_router.py) provides `/health`
for liveness. Readiness will be added by LIP-E006-F001 when the warm-up signal from
LIP-E005-F001 is wired.

**Architecture enforcement** is mechanical: import-linter has fifteen contracts —
1 generated-error gate (`no-direct-generated-error-imports`) +
4 leaf rules (`core-is-leaf`, `exceptions-is-leaf`, `schemas-is-leaf`,
`inference-model-is-leaf` — the last absorbs the model→repository forbidden
edge that previously lived in a separate contract) +
`features-are-independent` (cross-feature isolation) +
3 inference-internal layering rules (`inference-model-no-schemas`,
`inference-repository-no-schemas`, `inference-schemas-no-repository`) +
2 inference cross-layer rules (`inference-schemas-cross-layer`,
`inference-repository-cross-layer`) that forbid the inference feature
reaching up into `app.api`/`app.exceptions` from those layers +
4 api-cross-cutting rules (`api-exception-handlers-feature-agnostic`,
`api-request-id-middleware-feature-agnostic`,
`api-health-router-feature-agnostic`, `api-uses-inference-feature-root`).
See [apps/backend/architecture/import-linter-contracts.ini](../apps/backend/architecture/import-linter-contracts.ini)
for the full list. Each cross-cutting layer (`app.core`, `app.exceptions`, `app.schemas`)
cannot import features and cannot import each other; the inference feature's `model/`,
`repository/`, and `schemas/` are mutually constrained per the layer flow.

## What's NOT Built — feature-dev work

LIP feature nodes have landed in code: LIP-E001-F001 inference envelopes,
LIP-E003-F001 lifespan-managed OllamaClient, LIP-E003-F002 envelope↔Ollama translation,
LIP-E004-F004 problem+json, and LIP-E005-F003 launchd plist. The exact status set
shifts as features advance from `verifiable` to `implemented` — `grep -n '^status:'
graphs/LIP/LIP-*.md` reads the current source of truth so this paragraph cannot
silently drift behind reality. `service/` and `router/` arrive with LIP-E001-F002.
The project's seven epics (see [graphs/LIP/](../graphs/LIP/))
describe what feature-dev will build next:

- **LIP-E001 — Inference Contract & Happy Path:** envelope schemas, inference endpoint,
  service-layer orchestration.
- **LIP-E002 — Model Registry:** in-process metadata table mapping logical names to
  Ollama tags.
- **LIP-E003 — Ollama Backend Adapter:** httpx async client with configurable host,
  envelope <-> Ollama API translation.
- **LIP-E004 — Backpressure, Timeouts & Error Responses:** asyncio.Semaphore(1), bounded
  waiter count + 503, per-request timeout + 504, DomainError hierarchy expansion.
- **LIP-E005 — Lifecycle Management:** startup warm-up dummy inference, idle-shutdown
  timer, Ollama launchd plist.
- **LIP-E006 — Operational Visibility:** `/health` readiness gating + state-inspection
  endpoints (queue depth, model loaded, last request timestamp).
- **LIP-E007 — Documentation & Contract Discoverability:** README documenting the
  conceptual model, working httpx-based example consumer integration snippet.

## How Things Bind Together

**Service -> Ollama:** FastAPI service uses an `httpx.AsyncClient` with the host
configured via `LIP_OLLAMA_HOST` (defaulting to `http://localhost:11434`). The `LIP_`
prefix avoids colliding with Ollama daemon's own `OLLAMA_HOST`. The Ollama daemon
runs as a `launchd`-managed always-on service with `KEEP_ALIVE=300s` so the model
unloads from RAM shortly after idle.

**Service <- Consumer backend projects:** Consumers integrate via the auto-generated
OpenAPI schema and a hand-rolled httpx client. There is no generated client library
in v1.

**Error contracts:** `errors.yaml` generates Python exception classes the service raises,
plus a registry mapping error codes to classes for runtime lookup. `task check:errors`
verifies committed generated files match the YAML.

## What Is NOT Built — beyond v1

### No authentication or authorization
No auth middleware, no JWT, no OAuth, no per-project credentials. Local-network trust
is the entire security model in v1.

### No project-attribution structured logging
The request envelope's `metadata` field is reserved as a pass-through for
`project_id`, `request_id`, `trace_id` and similar caller-supplied attribution
keys. Per-project log routing, distributed cross-service tracing, and log
indexing / shipping pipelines are deferred — they require integration with
external systems that are out of v1 scope.

*In scope and shipped:* in-process `structlog` configuration, the per-request
`request_completed` JSON access log (method, path, status, duration_ms, request_id,
client addr), and the lifespan event family (`app_startup_started` /
`app_startup_completed` / `app_shutdown_started` /
`app_shutdown_completed` / `*_cancelled` / `*_failed`). See
[runbook.md](runbook.md) "Logs & triage" for the full event taxonomy. The
disambiguated-idea Observability section's carve-out (line 154) is the
authoritative pin.

### No quotas or rate limiting
Architectural foundation only (G4 from the disambiguated idea). The request envelope
and middleware composition support adding quotas later as additive changes.

### No streaming responses
Buffered JSON only. Streaming (SSE, WebSockets) is out of v1 scope.

### No tool / function calling
The envelope has no tools field in v1.

### No multi-model routing
One model loaded at a time fits the 16 GB Mini's RAM envelope.

### No persistent queue
In-memory `asyncio.Semaphore(1)` plus bounded waiter count is sufficient for <=4 serial
consumers.

### No inference response caching
Identical request inputs re-run the model. Caching is a future possibility under G4's
foundation.

### No Docker, no cloud, no portability
Native deployment to one specific 16 GB M4 Mac Mini base. No container packaging.
