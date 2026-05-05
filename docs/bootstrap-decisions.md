# Project Bootstrap — Decision Log

This document records the decisions made during the `project-bootstrap` skill run on
2026-04-27 that stripped this template repository down to LIP's actual scope.

## Decision log

| Capability | Decision | Reason | Source |
|---|---|---|---|
| Frontend (`apps/frontend/` entire tree) | STRIP | Zero UI features in 19 LIP feature stubs; backend-only project | autonomous |
| Database stack (SQLAlchemy, asyncpg, alembic, Testcontainers) | STRIP | Nothing persisted; LIP's "registry" is in-process | autonomous |
| Docker / docker-compose / both Dockerfiles | STRIP | Explicit constraint "Native deployment via uv and launchd; no Docker" | autonomous |
| Terraform (`infra/terraform/`) | STRIP | Local-only deployment, no cloud target | autonomous |
| i18n (i18next + locales + translation validator) | STRIP | Single solo developer, no end-users | autonomous |
| Money type (`app/types/money.py`) | STRIP | No monetary values anywhere | autonomous |
| Storybook | STRIP | No UI to document | autonomous |
| `Page[T]` schema | STRIP | No pagination needed in v1 | autonomous |
| `BaseModel` / `BaseRepository` / `BaseService` (`app/shared/`) | STRIP | All DB-coupled, no DB | autonomous |
| Widget reference slice (BE + FE) | STRIP | Example feature, not LIP | autonomous |
| `packages/api-client/` | STRIP | No FE to consume types | autonomous |
| `packages/error-contracts/` Python codegen | KEEP | CLAUDE.md mandate; LIP-E004-F004 | autonomous |
| `packages/error-contracts/` TS codegen + locale validator | STRIP | No FE to consume TS types; no locales | autonomous |
| `deploy.yml` workflow | STRIP | No cloud deploy | autonomous |
| Frontend CI jobs (`frontend-checks`, `api-client-checks`) | STRIP | FE gone | autonomous |
| Postgres service in `backend-checks` job | STRIP | No DB | autonomous |
| `pnpm-lock.yaml` + `pnpm-workspace.yaml` | STRIP | No Node | autonomous |
| Health endpoint (`/health`) | KEEP | LIP-E006-F001 | autonomous |
| `/ready` endpoint (DB-dependent in template) | STRIP | DB gone; LIP-E006-F001 will reintroduce with warm-up gating | autonomous |
| `app/api/request_id_middleware.py` Request ID | KEEP | Q1 user-answered (delegated). Powers `request_id` field in error envelope; G3 architectural foundation | user-answered |
| `app/api/request_id_middleware.py` Access Log | STRIP | Q2 user-answered (delegated). Structured-log emission out of v1 scope per Project Boundary | user-answered |
| `app/api/request_id_middleware.py` Security Headers | STRIP | Q3 user-answered (delegated). Local-network only, no internet exposure, no UI | user-answered |
| `app/api/request_id_middleware.py` CORS | STRIP | Q4 user-answered. Server-to-server httpx, not browsers | user-answered |
| Pre-commit / pre-push hooks | PARTIAL KEEP | Q5 user-answered (delegated). Backend hooks (ruff + format + pytest unit) kept; biome + vitest stripped (later expanded — current state lives in CLAUDE.md / docs/testing.md / `.pre-commit-config.yaml`). | user-answered |
| Dependabot | PARTIAL KEEP | Q6 user-answered (delegated). pip × 2 + github-actions kept; npm × 2 + terraform stripped. SQLAlchemy-stack group removed (no SQLAlchemy) | user-answered |
| Copilot PR review | STRIP | Q7 user-answered. Solo-dev project, no PR-review team | user-answered |
| Editor / VCS config (`.editorconfig`, `.gitattributes`, `.tool-versions`, `.gitignore`) | KEEP | skill default | autonomous |
| Import-linter contracts | KEEP | CLAUDE.md mandates layer rules; rewrote for LIP's repurposed feature-slice semantics | autonomous |
| `Taskfile.yml` | KEEP (rewrite) | Stripped FE / DB / Docker / Storybook tasks; kept backend + errors | autonomous |
| `CLAUDE.md` | KEEP (rewrite) | Stripped FE / DB / Money / Page forbidden patterns; kept Sacred Rules + cross-cutting | autonomous |
| `docs/reshape-plan.md` | STRIP | Template-internal meta-history, irrelevant to a bootstrapped project | autonomous |
| `docs/new-project-setup.md` | STRIP | Project-setup checklist for a fresh template clone, not for an already-bootstrapped project | autonomous |
| All other `docs/*.md` | KEEP (rewrite) | Scrubbed references to stripped capabilities; rebuilt content for LIP | autonomous |
| `docs/automerge.md` | KEEP (light edit) | Mostly generic Dependabot mechanics that still apply; status-checks list updated, deleted-doc links updated, header note added | autonomous |
| `TEMPLATE_FRICTION.md` | KEEP + append | Per skill spec, preserved historical entries and appended bootstrap-run entry with friction observations | autonomous |

## Execution steps

1. **Bulk directory deletes:** `apps/frontend/`, `apps/backend/alembic/`, `apps/backend/app/features/widget/`, `apps/backend/app/shared/`, `apps/backend/app/types/`, `infra/docker/`, `infra/compose/`, `infra/terraform/`, `infra/` (parent), `packages/api-client/`. Note: `infra/` was deleted at bootstrap and later re-created by LIP-E005-F003 (PR #9) with only `infra/launchd/` inside it (the Ollama plist), via [docs/ollama-launchd.md](ollama-launchd.md).
2. **Single-file deletes:** `apps/backend/app/core/database.py`, `apps/backend/app/schemas/page.py`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `.github/workflows/deploy.yml`, `.github/workflows/copilot-review.yml`. (`.env.example` was deleted then rewritten — counted under step 10's "Top-level rewrites" rather than re-listed here.)
3. **Widget _generated/ deletes:** 6 widget error class files (`widget_not_found_*`, `widget_name_conflict_*`, `widget_name_too_long_*`).
4. **Test deletes:** widget tests (unit + integration), DB-coupled tests (`test_rollback_canary.py`, `tests/integration/shared/`), Money tests (`tests/unit/types/`), Page tests (`tests/unit/schemas/`), config DB-validator test (`tests/unit/core/`), empty parent test packages (`tests/unit/features/`, `tests/unit/shared/`).
5. **Error-contracts deletes:** `packages/error-contracts/scripts/validate_translations.py`, `packages/error-contracts/tests/test_validate_translations.py`, `packages/error-contracts/src/`, `packages/error-contracts/package.json`.
6. **Backend code rewrites:** `pyproject.toml` (drop SQLAlchemy/asyncpg/alembic/testcontainers + alembic ignore), `app/main.py` (drop widget router + dispose_engine), `app/core/config.py` (drop database_url/cors_origins, add ollama_host), `app/api/request_id_middleware.py` (request_id only), `app/api/health_router.py` (liveness only), `app/exceptions/__init__.py` (drop widget exports), `app/exceptions/_generated/__init__.py` (drop widget imports), `app/exceptions/_generated/_registry.py` (drop widget entries), `architecture/import-linter-contracts.ini` (rewrite for layer-level forbidden contracts).
7. **Test rewrites:** `tests/integration/conftest.py` (no DB, ASGI transport client), `tests/integration/api/test_health.py` (just /health + request-id), `tests/contract/test_schemathesis.py` (drop DB env, drop widget endpoint assertions — file later replaced by `test_openapi_shape.py` + `test_problem_details_contract.py`), `tests/unit/exceptions/test_domain_errors.py` (substitute RateLimitedError for widget), `tests/unit/exceptions/test_error_handler.py` (substitute RateLimitedError for widget — file later moved to `tests/unit/api/test_exception_handlers.py`).
8. **Error-contracts edits:** `errors.yaml` (drop widget codes block).
9. **Config rewrites:** `.github/workflows/ci.yml`, `.github/dependabot.yml`, `.pre-commit-config.yaml`, `Taskfile.yml`.
10. **Top-level rewrites:** `CLAUDE.md`, `README.md`, `.env.example`.
11. **Doc rewrites:** `docs/architecture.md`, `docs/conventions.md`, `docs/decisions.md`, `docs/testing.md`, `docs/runbook.md`, `docs/ai-guide.md`, `docs/features.md`. Edit-only on `docs/automerge.md`. Append to `TEMPLATE_FRICTION.md`.

## Verification iterations

Single iteration. Every individual check passed on the first run.

| Check | Result |
|---|---|
| `uv sync --dev` (apps/backend) | OK — fresh venv, all deps installed |
| `uv sync --dev` (packages/error-contracts) | OK |
| `ruff check app/ tests/` | All checks passed |
| `ruff format --check app/ tests/` | 36 files already formatted |
| `pyright app/` | 0 errors, 0 warnings |
| `lint-imports --config architecture/import-linter-contracts.ini` | 3 contracts kept, 0 broken |
| `pytest tests/unit/` | 5/5 passed |
| `pytest tests/integration/` | 4/4 passed |
| `pytest tests/contract/` | 2/2 passed |
| Coverage (unit + integration) | 85.00% (threshold: 80%) |
| `pytest tests/` (error-contracts) | 6/6 passed |
| `errors:generate` | Regenerated files identical to hand-edited versions |

The aggregate `task check` reports `task check:errors` as failing because its
`git diff --exit-code apps/backend/app/exceptions/_generated/` step compares the working
tree against `HEAD` (commit `4b48e15`), which still contains the widget _generated
files that the bootstrap deleted. This failure is **expected and correct** for the
post-bootstrap pre-commit state; once the bootstrap is committed, the diff will be
empty and `task check:errors` will pass cleanly.

## Open follow-ups

These are tracked as feature-dev work, not bootstrap work:

- `apps/backend/uv.lock` was preserved through the bootstrap. `uv sync --dev` reconciled
  it cleanly, but the commit will record the lock with whatever transitive resolutions
  uv chose during bootstrap. Future Dependabot PRs will refresh against fresh trees.
- `_app` and unused-test-function pyright hints in the post-bootstrap exception-handler
  unit test (now at `tests/unit/api/test_exception_handler_registry.py`) are decorator-registered
  FastAPI route handlers that pyright thinks are unused. Pre-existing pattern; not
  introduced by bootstrap.
- LIP feature work (LIP-E001 through LIP-E007) is the next pipeline step. Use
  `feature-elicitation` per stub in `graphs/LIP/`.

## Resolved follow-ups

- *(2026-04-28)* `dependabot-lockfile-sync.yml` no longer contains pnpm-handling
  branches — the pnpm path was removed entirely post-bootstrap. See
  [TEMPLATE_FRICTION.md](../TEMPLATE_FRICTION.md) "Post-LIP-bootstrap (2026-04)"
  note for context.
