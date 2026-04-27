# CLAUDE.md

This file is the discipline contract for AI-assisted development on this repository.
Every rule is mandatory. "Forbidden" means "do not do this under any circumstances
without stopping and asking the user first." Violations are bugs.

## Project Overview

Local Inference Provider (LIP). FastAPI service on a 16 GB M4 Mac Mini base that wraps
a local Ollama daemon and exposes a stable backend-agnostic inference contract to up
to four locally-networked consumer backend projects. Single-developer project, native
deployment, no Docker, no database.

See [docs/disambigued-idea.md](docs/disambigued-idea.md) for the full project
specification. See [graphs/LIP/](graphs/LIP/) for the Project + Epic + Feature tree.

## Stack (do not deviate)

- Python 3.13, uv
- FastAPI, Pydantic v2, pydantic-settings, asyncio, httpx, structlog
- Inference backend: Ollama (Gemma 4 E2B in v1)
- Testing: pytest + pytest-asyncio + Schemathesis
- Task runner: Taskfile. No Make. No npm.
- When unsure about a library API, use Context7 to fetch current documentation
  rather than relying on training data.

## Sacred Rules

1. One class per file. Always. No exceptions. If you believe two classes belong
   together, stop and ask.
2. TDD. Always. Never write implementation before a failing test exists.
   Red -> green -> refactor.
3. No paradigm drift. One way to do each thing. If you think a second way is
   needed, stop and ask.
4. Run `task check` before declaring any work done. Never use `--no-verify`.

## Architecture

### Backend: Vertical Slices

```
app/core/           -- config, logging
app/api/            -- middleware, exception handler, health, shared deps
app/exceptions/     -- DomainError hierarchy (base + _generated/)
app/schemas/        -- ErrorResponse, ErrorBody, ErrorDetail
app/features/<feature>/ -- model, repository, service, router, schemas/
```

### Repurposed feature-slice layer semantics (no-database service)

LIP has no persistent database. The vertical-slice template's four layers are
preserved but with redefined semantics for a no-DB feature:

- `model/` — Pydantic value-objects (Message, ModelParams, ModelInfo).
  *Not* SQLAlchemy ORM models.
- `repository/` — the Ollama HTTP client wrapper. The "data-access" boundary
  in this project is *talking to Ollama*, not a database.
- `service/` — inference orchestration including the `asyncio.Semaphore(1)`.
- `router/` — FastAPI endpoints.
- `schemas/` — wire schemas (request and response envelopes).

### Layer Rules (mechanically enforced)

- Features cannot import from other features.
- Within a feature: router -> service -> repository -> model. No skipping.
- Schemas never import models. Models never import schemas.
- core/ never imports from features/.
- exceptions/ never imports from features/.

## Forbidden Patterns -- Backend

- Never use `print`. Use structlog.
- Never use `logging.getLogger`. Use structlog.
- Never use f-string log messages. Use structlog's key=value pairs:
  `logger.info("event_name", key=value)` not `logger.info(f"thing {value}")`.
- Never raise `HTTPException`. Raise a DomainError subclass.
- Never write a `try/except` that silently swallows errors. If you catch, re-raise or log.
- Never edit files in `exceptions/_generated/`. Edit errors.yaml, run task errors:generate.
- Never use `os.environ` or `os.getenv`. Use pydantic-settings.
- Never use `datetime.now()` without `tz=`. Use `datetime.now(UTC)`.
- Never use `datetime.utcnow()`.
- Never put business logic in route handlers. Handlers call one service method.
- Never put business logic in repositories. Repositories do data access only — in
  LIP's case, Ollama-API access only.
- Never write a sync `def` route handler. All handlers are `async def`.
- Never use `run_in_executor` or mix sync/async code paths.
- Never use global singletons, service locators, or DI container libraries. Use
  FastAPI Depends().
- Never import services or repositories directly in handlers. Wire via Depends() factories.
- Never import from one feature into another feature. Features are independent.
- Never import from `exceptions._generated` directly. Import from `exceptions`.
- Never add a feature without adding its slice to `architecture/import-linter-contracts.ini`.
- Never use `# type: ignore` without a comment explaining why.

## Forbidden Patterns -- Cross-cutting

- Never write implementation before a failing test exists.
- Never commit without running task check.
- Never use --no-verify.
- Never add an env var without adding it to the `Settings` class in `app/core/config.py`.
- Never add an error code without editing errors.yaml, running task errors:generate,
  and running task check:errors to verify the generated files are committed.
- Never skip a test level.
- Never introduce a new dependency without justification.
- Never write a test class. Use pytest functions.
- Never use unittest.TestCase. Use pytest.
- Never write a test with no assertions.

## Naming Conventions

- Python files: `snake_case.py`
- Python classes: `PascalCase` with role suffix (`InferenceService`, `OllamaRepository`)
- Python functions: `snake_case` verbs
- Python tests: `test_<unit>_<scenario>_<expected>`

## Error System

Source of truth: [packages/error-contracts/errors.yaml](packages/error-contracts/errors.yaml)
Generate: `task errors:generate` (produces Python classes in `_generated/`).
Verify: `task check:errors` (regenerates and runs `git diff --exit-code` to confirm
the generated files in source control match what the generator produces from the YAML).

To add a new error:
1. Add code to errors.yaml.
2. Run task errors:generate.
3. Write a test that raises the error and asserts the response shape.

## Testing Rules

Three levels mandatory in v1 (e2e arrives when the LIP feature router lands and there
is end-to-end behavior worth covering against a running Ollama):
1. **Unit** -- no network. Fast (<10s).
2. **Integration** -- httpx.AsyncClient via ASGITransport against the FastAPI app
   in-process. No DB. No Testcontainers.
3. **Contract** -- Schemathesis fuzzes the OpenAPI spec.

Type checker (Pyright strict) is a build failure, not a warning.

Excluded: property-based, performance, mutation, snapshot, fuzz beyond Schemathesis.

## Conventions (no code in template)

- **WebSockets:** if added, endpoints in api/v1/ws/, envelope `{type, payload, request_id}`,
  ConnectionManager class.
- **Caching:** interface first (get/set/delete), implementation second.
- **Rate limiting:** interface first, per-route config.
- **Background jobs:** job queue, never in request handlers.

## Dependabot

Close and delete any Dependabot PR that proposes a version older than latest.
Always use absolute latest versions for all dependencies.

**Auto-merge architecture** (see [docs/automerge.md](docs/automerge.md) for the full explainer):

- Dependabot-authored PRs that pass all required status checks are automatically
  squash-merged by [.github/workflows/dependabot-automerge.yml](.github/workflows/dependabot-automerge.yml).
  This is the ONE exception to the manual-Squash-button rule, documented in
  [docs/decisions.md ADR-010](docs/decisions.md).
- Never click merge on a green Dependabot PR. Let auto-merge handle it. If it's
  not auto-merging, something is wrong -- fix the root cause rather than merging
  manually.
- Never auto-merge a non-Dependabot PR. The workflow's `if:` guard scopes the
  exception strictly via `github.event.pull_request.user.login == 'dependabot[bot]'`.
  Human PRs merge manually via the green Squash button, always.
- Never use `github.actor` in any auto-merge guard condition. It reads the event
  triggerer, not the PR author, and will silently skip the workflow whenever a
  human interacts with a Dependabot PR (e.g. clicks "Update branch"). Always read
  `github.event.pull_request.user.login`.
- Never set `DEPENDABOT_AUTOMERGE_ENABLED` to `"true"` until the `main-protection`
  ruleset exists AND has the required status checks configured. `gh pr merge --auto`
  waits only for the checks declared on the ruleset; with no ruleset, `--auto` has
  nothing to wait for and merges immediately including red PRs. This is the PR #19
  incident documented in [TEMPLATE_FRICTION.md](TEMPLATE_FRICTION.md).
- Never bypass the ruleset. Never add anyone (including yourself) to the bypass
  list. Never disable the workflow with `--no-verify` or equivalent. If auto-merge
  is misbehaving, flip the variable to `"false"` (`gh variable set
  DEPENDABOT_AUTOMERGE_ENABLED --body "false"`) to disable it cleanly.

**Handling broken Dependabot PRs:**

- The repo ships [.github/workflows/dependabot-lockfile-sync.yml](.github/workflows/dependabot-lockfile-sync.yml)
  which auto-fixes the uv lockfile-gap bug on Dependabot PRs once the repo
  variable `DEPENDABOT_LOCKFILE_SYNC_ENABLED` is set to `"true"` and the repo
  secret `DEPENDABOT_LOCKFILE_SYNC_PAT` contains a fine-grained PAT.
- If a Dependabot PR is `BEHIND` main (stale base), never click "Update branch"
  in the UI -- it attributes the push to you, not to Dependabot, and can cause
  Dependabot to "disavow" the PR afterward. Instead, use the server-side
  update-branch API: `gh api -X PUT repos/OWNER/REPO/pulls/NUMBER/update-branch`.
  This triggers a rebase attributed to the API call, not a human user.
- If Dependabot has already disavowed a PR, `@dependabot rebase` will not work.
  Use the same `PUT /update-branch` escape hatch -- it is not owned by Dependabot
  and works regardless of disavowal state.
- If a Dependabot PR hits a rebase conflict because sibling PRs have merged
  changes to adjacent lines of the same manifest file, close it and open a
  manual replacement PR. Then add a `groups:` entry to
  [.github/dependabot.yml](.github/dependabot.yml) so the ecosystem cannot
  cascade-conflict again.
