# Runbook

Operational guide for running and maintaining LIP.

## Prerequisites

- Python 3.13
- `uv` (https://docs.astral.sh/uv/)
- Ollama installed natively on macOS, with `gemma4:e2b` pulled

```bash
brew install ollama
ollama pull gemma4:e2b
```

The Ollama daemon is configured to run as a `launchd` service (the plist will be added
by LIP-E005-F003 during feature-dev) with `KEEP_ALIVE=300s`, `NUM_PARALLEL=1`,
`MAX_LOADED_MODELS=1`, `FLASH_ATTENTION=1`, `KV_CACHE_TYPE=q8_0`.

## Local Development

```bash
# Install dependencies
cd apps/backend
uv sync --dev

# Start the service with hot reload
task dev
# Equivalent: uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Service: http://127.0.0.1:8000
- `/health` — liveness probe
- `/openapi.json` — auto-generated OpenAPI schema
- `/docs` — Swagger UI (dev only)
- `/redoc` — ReDoc (dev only)

## Testing

```bash
# All checks (run before declaring work done)
task check

# All tests
task test

# By level
task test:unit
task test:integration
task test:contract
```

## Error System

```bash
# After editing errors.yaml:
task errors:generate
task check:errors  # verifies generated files match committed files
```

## Linting & Formatting

```bash
task lint
task format
```

## Health Check

- Liveness: `GET /health` -> `{"status": "ok"}`
- Readiness: will be added by LIP-E006-F001 when the warm-up signal lands during feature-dev.

## Troubleshooting

### Service won't start

- Check that `pyproject.toml` and `uv.lock` are in sync: `uv sync --dev`
- Check that Python 3.13 is available: `uv python install 3.13`

### Tests fail with import errors

- Run `uv sync --dev` from `apps/backend/` to install all dev dependencies.
- Run from the `apps/backend/` directory (or use `task` which handles `cd` for you).

### Ollama daemon not reachable (after LIP-E003 lands)

- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Verify the Gemma model is pulled: `ollama list | grep gemma`
- Override the host if needed: `OLLAMA_HOST=http://localhost:11500 uv run uvicorn ...`
