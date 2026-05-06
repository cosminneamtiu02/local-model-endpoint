# Architecture

## System Overview

```
+----------------------------+
| Consumer backend project   |  (1 today; up to 4 within 12 months)
+-------------+--------------+
              |
              | HTTP (httpx)
              v
+-------------+--------------+
| Local Inference Provider   |  FastAPI, Pydantic v2
| (this service)             |  asyncio.Semaphore(1) gating
+-------------+--------------+
              |
              | HTTP (httpx)
              v
+-------------+--------------+
| Ollama daemon (launchd)    |  KEEP_ALIVE=300s
| Gemma 4 E2B (in v1)        |
+----------------------------+
```

## Backend Architecture: Vertical Slices

```
apps/backend/
├── app/
│   ├── core/               -- config.py, logging.py. Cross-cutting infrastructure.
│   ├── api/                -- middleware (request_id only), exception handler, health, shared deps.
│   ├── exceptions/         -- DomainError base (base.py) + generated subclasses (_generated/).
│   ├── schemas/            -- ProblemDetails, ProblemExtras, ValidationErrorDetail, HealthResponse, wire_constants. Shared response shapes (RFC 7807 problem+json + liveness); wire_constants centralizes the UUID regex, request-id length, instance-path cap, RFC 7807 about:blank type URI, X-Request-ID header spelling, and the application/problem+json media-type / Content-Language values shared across api and schemas — see the module docstring for rationale.
│   └── features/
│       └── <feature>/      -- One folder per feature. Self-contained vertical slice.
│           ├── model/          -- Pydantic value-objects (Message, ModelParams, ContentPart, OllamaChatResult; ModelInfo lands with LIP-E002-F001)
│           ├── repository/     -- Ollama HTTP client wrapper (the "data" boundary)
│           ├── service/        -- Inference orchestration (Semaphore, registry lookup)
│           ├── router/         -- FastAPI endpoints
│           └── schemas/        -- Wire schemas (request and response envelopes)
├── architecture/
│   └── import-linter-contracts.ini  -- Layer + feature-isolation contracts
└── tests/
    ├── unit/               -- Fast, no network. <10s.
    ├── integration/        -- httpx.AsyncClient + ASGITransport in-process.
    └── contract/           -- OpenAPI canary + RFC 7807 wire-shape (Schemathesis fuzz arrives with LIP-E001-F002).

infra/
└── launchd/
    └── com.lip.ollama.plist.tmpl  -- User-scope launchd agent template (__HOME__ substituted by `task ollama:install`).
```

The inference feature is partially scaffolded: `model/`, `repository/`, and wire
`schemas/` are landed (LIP-E001-F001, LIP-E003-F001, LIP-E003-F002 in
[graphs/LIP/](../graphs/LIP/)), plus the cross-cutting LIP-E004-F004 RFC 7807
problem+json layer (in `app/api/exception_handler_registry.py` + `app/schemas/`) and LIP-E005-F003
launchd agent (in `infra/launchd/`). `service/` and `router/` arrive with
LIP-E001-F002 per ADR-011 lazy scaffolding. The directory structure above
describes where each remaining layer will live.

### Layer Flow (within a feature)

```
HTTP Request
    |
    v
router        Thin handler. Declares Depends(), calls service, returns result.
    |
    v
service       Inference orchestration. Semaphore-gated. Resolves model via registry.
    |
    v
repository    Ollama HTTP client (data-access boundary).
    |
    v
model         Pydantic value-objects passed through the layers, plus pure
              envelope <-> Ollama translation helpers (ollama_translation.py).
```

No layer skipping. Router never calls Ollama directly. Repository never owns service-level
concerns like the semaphore.

### Error Flow

```
Ollama HTTP error
    |
    v
Repository catches (httpx.RequestError or non-2xx) and raises a typed DomainError
    |
    v
Service may catch and re-raise with more specific typed params, or let it propagate
    |
    v
Exception handler serializes to RFC 7807 application/problem+json (ProblemDetails)
    |
    v
Consumer receives a structured error envelope it can program against
```

## Lifecycle (on-demand)

LIP's FastAPI service is on-demand, not always-on (G6 from
[docs/disambiguated-idea.md](disambiguated-idea.md)). A consumer's first request
through the local network triggers `task dev`-style wake-up; the service warms
the model with a dummy inference (LIP-E005-F001) and starts serving. Once
serving, an idle-shutdown timer (LIP-E005-F002) tears the FastAPI process down
after 10 minutes without inbound requests, freeing RAM for desktop work.
Ollama itself is the always-on substrate underneath — it stays bootstrapped
through the user-scope `launchd` agent and unloads the model from RAM 5 min
after the last request via `OLLAMA_KEEP_ALIVE=300s`. See
[docs/disambiguated-idea.md](disambiguated-idea.md) for the full lifecycle spec
and [docs/ollama-launchd.md](ollama-launchd.md) for the Ollama side.

## API Versioning

- Inference endpoints: `/v1/...` (per LIP-E001-F002, "domain-language path,
  not OpenAI-compat").
- Health: `/health` (root, unversioned).

## Packages

- `packages/error-contracts/` — Error code definitions (errors.yaml), Python codegen,
  generator tests. No frontend codegen in v1.

## Infrastructure

- Native deployment via `uv` and `launchd`. No Docker, no cloud.
- Ollama runs as a `launchd`-managed always-on daemon (small idle footprint).
  See [docs/ollama-launchd.md](ollama-launchd.md) for the plist, env-var
  rationale, and operator commands.
- The FastAPI service is on-demand: launched by consumers, self-shuts after 10 min idle
  (LIP-E005-F002 will implement the timer).
