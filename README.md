# Local Inference Provider (LIP)

A FastAPI service on a 16 GB M4 Mac Mini base that wraps a local Ollama daemon and
exposes a stable backend-agnostic inference contract to up to four locally-networked
consumer backend projects.

See [docs/disambiguated-idea.md](docs/disambiguated-idea.md) for the full project description
and [graphs/LIP/](graphs/LIP/) for the Project + Epic + Feature tree.

## Tech Stack

- **Backend**: Python 3.13, FastAPI, Pydantic v2, pydantic-settings, asyncio, httpx, structlog
- **Inference backend**: Ollama running natively on macOS (Gemma 4 E2B in v1)
- **Testing**: pytest + pytest-asyncio (Schemathesis lands with LIP-E001-F002 per [ADR-011](docs/decisions.md))
- **Tooling**: Taskfile, Ruff, Pyright, import-linter, uv, pre-commit, pytest-cov, pip-audit, detect-secrets

## Quick Start

```bash
# Prerequisites: Python 3.13, uv, Task

# Install Ollama once. The plist template hardcodes `/opt/homebrew/bin/ollama`
# (the Apple Silicon Homebrew default). Install Ollama at that path before
# running `task ollama:install`, or edit the plist per docs/ollama-launchd.md
# before installing — `task ollama:install` itself will succeed but the
# agent will fail to start when launchd tries to exec a missing binary.
brew install ollama

# Install the always-on Ollama launchd agent + pull the model
task ollama:install && ollama pull gemma4:e2b

cd apps/backend
uv sync --dev

# Also sync the codegen workspace so `task check:errors` / `task errors:generate`
# can run from the repo root without an "environment not found" error.
cd ../../packages/error-contracts && uv sync --dev && cd -

# Run the service
task dev
```

`task dev` runs `uv run python -m app --reload` under the hood, which goes through `app/__main__.py` so Settings (`LIP_BIND_HOST` / `LIP_BIND_PORT`) is the single source of truth for binding.

## Commands

| Command | Description |
|---|---|
| `task dev` | Start backend with hot reload |
| `task check` | Run lint, format, lockfile, types, architecture, coverage-gated tests, error contracts, plist, audit, secrets |
| `task test` | Run all tests (unit + integration + contract) |
| `task test:unit` | Run unit tests |
| `task test:integration` | Run integration tests (in-process via ASGI transport) |
| `task test:contract` | Run contract tests (OpenAPI canary + RFC 7807 wire shape; full Schemathesis fuzz arrives with LIP-E001-F002) |
| `task lint` | Run ruff lint |
| `task format` | Run ruff format |
| `task errors:generate` | Generate Python error classes from errors.yaml |
| `task check:errors` | Verify error contracts are up to date |
| `task ollama:install` | Install + bootstrap the Ollama launchd agent |
| `task ollama:uninstall` | Bootout + remove the Ollama launchd agent |
| `task ollama:status` | Print launchctl state for the Ollama agent |
| `task check:plist` | Validate the Ollama plist with `plutil -lint` (macOS) |

## Documentation

- [Disambiguated idea](docs/disambiguated-idea.md) — full project description
- [Brainstorm](docs/brainstorm.md) — historical pre-disambiguation brief, superseded by `disambiguated-idea.md`
- [Features](docs/features.md) — catalog of features in the box
- [Architecture](docs/architecture.md) — vertical-slice layout and layer rules
- [Conventions](docs/conventions.md) — naming, schemas, and other code-style rules
- [Decisions](docs/decisions.md) — current architectural decision records
- [Bootstrap decisions](docs/bootstrap-decisions.md) — record of decisions taken during the LIP bootstrap from the template
- [AI guide](docs/ai-guide.md) — overview of the AI-assisted scaffold (skills, graphs, contracts)
- [Testing](docs/testing.md) — three-level test strategy in v1
- [Runbook](docs/runbook.md) — day-to-day operational commands
- [Ollama Launchd Agent](docs/ollama-launchd.md) — one-time install + operator commands
- [Auto-merge](docs/automerge.md) — Dependabot auto-merge architecture and runbook

## AI-Assisted Development

See [CLAUDE.md](CLAUDE.md) for the discipline contract governing AI-assisted work.
See [graphs/LIP/](graphs/LIP/) for the Project + Epic + Feature tree.

## License

See [LICENSE](LICENSE).
