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
app/
├── core/               -- config, logging. Cross-cutting infrastructure.
├── api/                -- middleware (request_id only), exception handler, health, shared deps.
├── exceptions/         -- DomainError base (base.py) + generated subclasses (_generated/).
├── schemas/            -- ErrorResponse, ErrorBody, ErrorDetail. Shared response shapes.
└── features/
    └── <feature>/      -- One folder per feature. Self-contained vertical slice.
        ├── model/          -- Pydantic value-objects (Message, ModelParams, ModelInfo)
        ├── repository/     -- Ollama HTTP client wrapper (the "data" boundary)
        ├── service/        -- Inference orchestration (Semaphore, registry lookup)
        ├── router/         -- FastAPI endpoints
        └── schemas/        -- Wire schemas (request and response envelopes)
```

The LIP feature itself does not yet exist in code — it is scaffolded during feature-dev.
The directory structure above describes where it will live. See [graphs/LIP/](../graphs/LIP/)
for the planned features.

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
repository    Ollama HTTP client. Translates envelope <-> Ollama API.
    |
    v
model         Pydantic value-objects passed through the layers.
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
Exception handler serializes to JSON: {error: {code, params, details, request_id}}
    |
    v
Consumer receives a structured error envelope it can program against
```

## API Versioning

- Inference endpoints: `/api/v1/...` (path TBD by LIP-E001-F002).
- Health: `/health` (root, unversioned).

## Packages

- `packages/error-contracts/` — Error code definitions (errors.yaml), Python codegen,
  generator tests. No frontend codegen in v1.

## Infrastructure

- Native deployment via `uv` and `launchd`. No Docker, no cloud.
- Ollama runs as a `launchd`-managed always-on daemon (small idle footprint).
- The FastAPI service is on-demand: launched by consumers, self-shuts after 10 min idle
  (LIP-E005-F002 will implement the timer).
