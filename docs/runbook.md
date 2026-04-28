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

The Ollama daemon is configured to run as a `launchd` service via the plist at
`infra/launchd/com.lip.ollama.plist` (added by PR #9 / LIP-E005-F003) with
`KEEP_ALIVE=300s`, `NUM_PARALLEL=1`, `MAX_LOADED_MODELS=1`, `FLASH_ATTENTION=1`,
`KV_CACHE_TYPE=q8_0`. Run `task ollama:install` to install it; see
[docs/ollama-launchd.md](ollama-launchd.md) for env-var rationale and
customization.

## Local Development

```bash
# Install dependencies
cd apps/backend
uv sync --dev

# Start the service with hot reload
task dev
# Equivalent: uv run python -m app --reload (host/port from Settings)
```

Service: http://127.0.0.1:8000 (defaults; override via `LIP_BIND_HOST` / `LIP_BIND_PORT` — see *Configuration* below)
- `/health` — liveness probe
- `/openapi.json` — auto-generated OpenAPI schema
- `/docs` — Swagger UI (dev only)
- `/redoc` — ReDoc (dev only)

## Configuration

All runtime configuration is through `pydantic-settings`. The full canonical list
of env vars lives in [`apps/backend/.env.example`](../apps/backend/.env.example);
the table below summarizes the production-relevant ones. The `.env` file is
resolved relative to the runtime cwd — `task dev` cd's into `apps/backend/` first,
so the lookup is `apps/backend/.env`. Running `python -m app` from the repo root
will not find a `.env`; always launch via `task dev` (or `cd apps/backend` first).

| Env var | Default | Meaning |
|---|---|---|
| `LIP_APP_ENV` | `development` | One of `development` / `test` / `production`. Production hides `/docs`, `/redoc`, `/openapi.json` and emits JSON logs. |
| `LIP_LOG_LEVEL` | `info` | One of `debug` / `info` / `warning` / `error` / `critical`. |
| `LIP_OLLAMA_HOST` | `http://localhost:11434` | The local Ollama daemon URL. The `LIP_` prefix avoids colliding with Ollama's own `OLLAMA_HOST`. Validator rejects non-private hosts unless `LIP_ALLOW_EXTERNAL_OLLAMA=true`. |
| `LIP_ALLOW_EXTERNAL_OLLAMA` | `false` | Escape hatch acknowledging that LIP will forward consumer prompts to a non-private host. |
| `LIP_BIND_HOST` | `127.0.0.1` | Interface for `task dev` / `python -m app`. Validator rejects `0.0.0.0` / `::` unless `LIP_ALLOW_PUBLIC_BIND=true` because LIP has no auth. |
| `LIP_BIND_PORT` | `8000` | Port (1024–65535). |
| `LIP_ALLOW_PUBLIC_BIND` | `false` | Escape hatch for binding all interfaces. Required to acknowledge the no-auth posture before LAN-exposing. |

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

## Ollama agent

Operator commands for the user-scope `launchd` agent that keeps the Ollama
daemon running (see [docs/ollama-launchd.md](ollama-launchd.md) for env-var
rationale and customization):

| Command | Description |
|---|---|
| `task ollama:install` | Copy the plist to `~/Library/LaunchAgents/` and bootstrap the agent into the GUI session domain |
| `task ollama:uninstall` | Bootout the agent and remove the installed plist |
| `task ollama:status` | Print the launchctl state (use to verify the env vars made it through) |
| `task check:plist` | Validate the plist with `plutil -lint` (macOS only; also wired into `task check`) |

`task ollama:install` is **not** idempotent — to apply plist edits, run
`task ollama:uninstall && task ollama:install`. `launchctl kickstart -k`
restarts the running daemon under the in-memory plist; it does not re-read
the on-disk plist.

## Troubleshooting

### Service won't start

- Check that `pyproject.toml` and `uv.lock` are in sync: `uv sync --dev`
- Check that Python 3.13 is available: `uv python install 3.13`

### Tests fail with import errors

- Run `uv sync --dev` from `apps/backend/` to install all dev dependencies.
- Run from the `apps/backend/` directory (or use `task` which handles `cd` for you).

### Ollama daemon not reachable

- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Verify the Gemma model is pulled: `ollama list | grep gemma`
- Override the host if needed: `LIP_OLLAMA_HOST=http://127.0.0.1:11500 task dev` (the
  Settings field is `ollama_host` and reads from the `LIP_`-prefixed env var;
  setting plain `OLLAMA_HOST` would target the daemon, not LIP).

## Supply-chain audit

```bash
task check:audit  # runs pip-audit on the locked deps; surfaces known CVEs
```

Not wired into `task check` because pip-audit hits PyPI and a transient
advisory bump should not block a local commit. Run on demand and as part of
release prep.
