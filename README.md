# Local Inference Provider (LIP)

A FastAPI service on a 16 GB M4 Mac Mini base that wraps a local Ollama daemon and
exposes a stable backend-agnostic inference contract to up to four locally-networked
consumer backend projects.

See [docs/disambigued-idea.md](docs/disambigued-idea.md) for the full project description
and [graphs/LIP/](graphs/LIP/) for the Project + Epic + Feature tree.

## Tech Stack

- **Backend**: Python 3.13, FastAPI, Pydantic v2, asyncio, httpx, structlog
- **Inference backend**: Ollama running natively on macOS (Gemma 4 E2B in v1)
- **Testing**: pytest + pytest-asyncio + Schemathesis
- **Tooling**: Taskfile, Ruff, Pyright, import-linter, uv

## Quick Start

```bash
# Prerequisites: Python 3.13, uv, Ollama with gemma4:e2b pulled

cd apps/backend
uv sync --dev

# Run the service
task dev
```

`task dev` runs `uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` under the hood; reach for the bare `uv run` form only if you need to override one of those flags.

## Commands

| Command | Description |
|---|---|
| `task dev` | Start backend with hot reload |
| `task check` | Run all linters, type checkers, architecture, tests, error contracts |
| `task test` | Run all tests (unit + integration + contract) |
| `task test:unit` | Run unit tests |
| `task test:integration` | Run integration tests (in-process via ASGI transport) |
| `task test:contract` | Run contract tests (Schemathesis) |
| `task lint` | Run ruff lint |
| `task format` | Run ruff format |
| `task errors:generate` | Generate Python error classes from errors.yaml |
| `task check:errors` | Verify error contracts are up to date |

## Documentation

- [Disambiguated idea](docs/disambigued-idea.md) — full project description
- [Features](docs/features.md) — catalog of features in the box
- [Architecture](docs/architecture.md) — vertical-slice layout and layer rules
- [Conventions](docs/conventions.md) — naming, schemas, and other code-style rules
- [Decisions](docs/decisions.md) — current architectural decision records
- [Bootstrap decisions](docs/bootstrap-decisions.md) — record of decisions taken during the LIP bootstrap from the template
- [AI guide](docs/ai-guide.md) — overview of the AI-assisted scaffold (skills, graphs, contracts)
- [Testing](docs/testing.md) — three-level test strategy in v1
- [Runbook](docs/runbook.md) — day-to-day operational commands
- [Auto-merge](docs/automerge.md) — Dependabot auto-merge architecture and runbook

## AI-Assisted Development

See [CLAUDE.md](CLAUDE.md) for the discipline contract governing AI-assisted work.
See [graphs/LIP/](graphs/LIP/) for the Project + Epic + Feature tree.

## License

See [LICENSE](LICENSE).
