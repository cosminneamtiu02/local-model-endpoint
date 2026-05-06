# Contributing

> Read [CLAUDE.md](CLAUDE.md) first — it is the discipline contract. Every rule is mandatory.

## Getting Started

Follow the README's Quick Start through `task dev` — it is the canonical
setup sequence and includes the Ollama daemon prerequisites that `task dev`
needs at lifespan startup. Summary:

1. Clone the repository.
2. Install prerequisites: Python 3.13, uv (https://docs.astral.sh/uv/), Task (https://taskfile.dev/), and Ollama (`brew install ollama`).
3. Install + run the launchd-managed Ollama daemon: `task ollama:install && ollama pull gemma4:e2b`.
4. Sync workspaces: `cd apps/backend && uv sync --dev`, then `cd ../../packages/error-contracts && uv sync --dev`.
5. Run `task dev` to start the backend with hot reload.

## Development Setup

See [docs/architecture.md](docs/architecture.md) for the system architecture
and [docs/conventions.md](docs/conventions.md) for coding conventions.

## Code Style

- **Python**: Ruff (ALL rules), Pyright strict.
- **Run `task check` before pushing.** This is the same suite CI runs (lint,
  format, lockfile, types, architecture, tests, coverage, error contracts,
  plist, audit, secrets).
- **PR titles** use [Conventional Commits](https://www.conventionalcommits.org/)
  because the squash-merge title becomes the commit on `main`. Individual
  commit messages on a feature branch are not required to follow Conventional
  Commits — the PR title is what lands.

## Pull Request Process

1. Create a feature branch from `main`
2. Write tests first (TDD)
3. Run `task check` before pushing
4. Open a PR against `main`
5. Ensure CI passes
6. Squash merge

## Architecture

Read [CLAUDE.md](CLAUDE.md) — **the discipline contract; read first.** It
contains the complete list of rules and forbidden patterns.
