# Template Friction Log

> **About this file.** LIP operational incident log. Originally tracked friction
> observed when using the upstream template repo; the historical entries below
> are preserved for institutional memory but reference template-era PR numbers,
> ecosystems, and incidents that predate this project. New entries are added
> only for LIP-specific operational incidents (with their resolutions); the
> file is no longer used to feed a future "template v2" effort.

## Friction Points

<!-- Add entries as: ### Date - Description -->
<!-- Example: ### 2026-05-01 - BaseRepository.list() doesn't support filtering -->

### 2026-04-12 — Dependabot doesn't regenerate pnpm workspace lockfile — ✅ FIXED at template level

(PR numbers reference the upstream template repo; not LIP PR numbers.)

When the monorepo uses a single root `pnpm-lock.yaml` with per-workspace `package.json` files, Dependabot updates only the manifest and silently fails to regenerate the lockfile. CI then rejects every Dependabot PR with `ERR_PNPM_OUTDATED_LOCKFILE` when `pnpm install --frozen-lockfile` runs. Observed on `@tanstack/react-query`, `@tanstack/react-router`, `@tanstack/router-devtools`, `@tanstack/router-plugin` — four individual PRs that all had the same failure mode.

**Template-level workaround we shipped first:** aggressive `groups:` in [.github/dependabot.yml](.github/dependabot.yml) so at least the N broken PRs become 1 broken PR instead of N. Also a runbook entry in [docs/automerge.md](docs/automerge.md) for the close-and-replace manual workflow.

**Template-level fix we shipped next:** [.github/workflows/dependabot-lockfile-sync.yml](.github/workflows/dependabot-lockfile-sync.yml) — a new workflow that fires on every Dependabot PR, detects whether the PR modified `package.json` or `pyproject.toml` without the corresponding lockfile, runs the package manager in regeneration mode, and pushes the updated lockfile back to the PR branch as a follow-up commit. Composes naturally with the existing auto-merge workflow: sync fires → pushes lockfile fix → new `synchronize` event → auto-merge workflow re-fires (harmlessly idempotent) and CI re-runs on the fixed commit → checks pass → auto-merge queue executes the squash-merge. Net result: a Dependabot PR with the lockfile-gap bug goes from "stuck red indefinitely" to "auto-merges cleanly" within about 2–3 minutes, with zero human intervention.

**Prerequisites for the sync workflow to function** (downstream project concern — see [docs/automerge.md#setup](docs/automerge.md#setup) for the canonical numbered list, items 1–5):
1. A fine-grained PAT with `Contents: Read and write` + `Pull requests: Read and write` scoped to the project's one repo. Must be a PAT, not `GITHUB_TOKEN`, because `GITHUB_TOKEN`-authored pushes do not trigger subsequent workflow runs and CI would never re-run on the fixed commit.
2. Repo secret `DEPENDABOT_LOCKFILE_SYNC_PAT` set to that PAT.
3. Repo variable `DEPENDABOT_LOCKFILE_SYNC_ENABLED` set to `"true"`.

Both the variable and secret are unset on the template itself so the workflow is dormant. Downstream projects enable them after the `main-protection` ruleset is in place (see [docs/automerge.md#setup](docs/automerge.md#setup)).

**Backend equivalent:** `uv sync --dev` is lenient about `pyproject.toml` / `uv.lock` divergence, so backend Dependabot PRs don't surface the bug as loudly, but `uv.lock` in git is silently out of sync with the manifest after each merge. The new lockfile-sync workflow **also** handles backend: it runs `uv lock` in `apps/backend` and `packages/error-contracts` when those manifests changed, committing the regenerated lockfile back. This means `uv.lock` stays authoritative in git without needing to switch CI to `uv sync --frozen`.

**Upstream bug status:** still unfixed in `dependabot-core`. The workaround workflow is tool-side infrastructure — the moment dependabot-core ships a proper fix for pnpm workspaces, the sync workflow becomes redundant and can be deleted. Until then, it's load-bearing.

**Post-LIP-bootstrap (2026-04):** the pnpm path was removed entirely from `dependabot-lockfile-sync.yml`; only the uv code path ships in this repo.

### 2026-04-12 — `github.actor` is the wrong field for Dependabot auto-merge workflows — ✅ FIXED at template level

(PR numbers reference the upstream template repo; not LIP PR numbers.)

The template's initial auto-merge workflow pattern (which we shipped in the first iteration of [.github/workflows/dependabot-automerge.yml](.github/workflows/dependabot-automerge.yml)) used `github.actor == 'dependabot[bot]'` as the scope guard. `github.actor` reads the current event's triggerer, not the PR author. When a human clicks "Update branch" on a Dependabot PR, the resulting `synchronize` event's actor is the human, and the guard evaluates false. All five backend Dependabot PRs were stuck in this state for ~10 minutes until the guard was fixed.

**Template-level fix we shipped:** hotfix changed the guard to `github.event.pull_request.user.login == 'dependabot[bot]'`, which reads the PR author from the event payload. That field stays `dependabot[bot]` for the lifetime of the PR regardless of who triggers individual events. Inline workflow comment + ADR-010 guard-condition paragraph + CLAUDE.md Dependabot section + [docs/automerge.md Incident 2](docs/automerge.md) all explicitly document the correct pattern so it cannot be silently reintroduced.

**Why the trap is so common:** GitHub's own auto-merge docs recommended `github.actor` until late 2023. The wrong pattern propagated to hundreds of public workflow examples. Any future edit that "simplifies" the guard based on a search result will reintroduce the bug.

### 2026-04-12 — Auto-merge without a ruleset silently merges red PRs — ✅ FIXED at template level

(PR numbers reference the upstream template repo; not LIP PR numbers.)

The template's auto-merge workflow called `gh pr merge --auto --squash` directly, trusting that GitHub's merge queue would wait for required status checks before actually merging. This is true **if and only if a ruleset with required status checks exists**. With no ruleset, `--auto` has nothing to wait for and merges immediately, including PRs with failing CI.

Observed on PR #19 (the first grouped TanStack Dependabot PR after the grouping config landed): it merged on the spot with `frontend-checks` and `api-client-checks` red because the workflow was deployed before the `main-protection` ruleset was created. Main was broken for ~2 minutes until a follow-up PR with the lockfile fix race-landed and accidentally repaired it.

**Template-level fix we shipped:** hotfix added a `DEPENDABOT_AUTOMERGE_ENABLED` repo variable. The workflow's `if:` guard now requires the variable to be literally `"true"` before running. The user must set the variable only after verifying the ruleset exists with all required status checks — see [docs/automerge.md#setup](docs/automerge.md#setup) items 1–5 for the canonical sequencing. The variable also serves as the emergency kill switch (`gh variable set DEPENDABOT_AUTOMERGE_ENABLED --body "false"`).

**Root cause of the original assumption:** conflated `allow_auto_merge` (a repo setting controlling the UI button) with "the thing that gates --auto". They are not the same. `--auto` is gated by the *ruleset's* required status checks, not the repo setting.

### 2026-04-12 — UI "Update branch" button causes Dependabot to disavow PRs — ✅ WORKAROUND documented

(PR numbers reference the upstream template repo; not LIP PR numbers.)

When a human clicks "Update branch" on a Dependabot PR, GitHub performs the rebase and attributes the resulting push to the human. Dependabot's safety policy then marks the PR as "edited by someone other than Dependabot" and refuses to run `@dependabot rebase` / `@dependabot recreate` commands on it thereafter.

Observed on all 5 backend Dependabot PRs during the auto-merge setup session. Once disavowed, there was no Dependabot-controlled path to unstick them.

**Template-level workaround we found:** use the server-side `PUT /repos/OWNER/REPO/pulls/NUMBER/update-branch` API endpoint instead of the UI button. This endpoint is not owned by Dependabot, works regardless of disavowal state, and respects the repo's configured merge method (squash-only in our case). Documented in [CLAUDE.md](CLAUDE.md), [docs/automerge.md](docs/automerge.md), and historically in the template's new-project setup checklist.

**Template-level fix still needed:** GitHub's UI "Update branch" button should call this same server-side endpoint when clicked on a Dependabot PR, so disavowal doesn't happen. That's a GitHub product decision, not something we can fix at the template level. Document avoidance only.

### 2026-04-12 — Adjacent manifest line edits produce rebase-conflict cascades — ✅ FIXED at template level

(PR numbers reference the upstream template repo; not LIP PR numbers.)

When multiple Dependabot PRs modify adjacent lines in the same manifest file (e.g. `pyproject.toml`'s dependency list), merging them sequentially produces 3-way merge conflicts on the later PRs. The conflicts are contextual, not semantic — each PR's one-line edit would apply cleanly if the surrounding context hadn't drifted. Observed on PR #16 (`asyncpg`) after PRs #12–#15 merged bumps to `testcontainers`, `sqlalchemy`, `alembic`, `schemathesis`.

**Template-level fix we shipped:** aggressive `groups:` in [.github/dependabot.yml](.github/dependabot.yml) for every ecosystem where interlocking dependencies touch the same manifest file. Specifically: `sqlalchemy-stack` (sqlalchemy + alembic + asyncpg), `fastapi-stack`, `pydantic`, `pytest`, `tanstack`, `react`, `storybook`, `vitest`, `testing-library`, `tailwind`, `i18next`, `dinero`.

**Takeaway codified:** when you see a fifth Dependabot PR for the same ecosystem, it's almost always doomed to cascade-conflict. Add a group and don't merge siblings individually.

### 2026-04-27 — LIP project bootstrap stripped the template to backend-only

The Local Inference Provider (LIP) project was bootstrapped from this template using the `project-bootstrap` skill on 2026-04-27. The template was stripped to its backend-only foundation and tailored to LIP's specifications:

**Stripped (whole directories):**
- `apps/frontend/` — entire React tree, Storybook, i18n, locales, FE tests
- `infra/docker/` + `infra/compose/` + `infra/terraform/` + `infra/` parent dir — no Docker, no cloud
- `packages/api-client/` — no FE to consume types
- `apps/backend/alembic/` — no database
- `apps/backend/app/features/widget/` — reference slice not relevant to LIP
- `apps/backend/app/shared/` — DB-coupled BaseModel/BaseRepository/BaseService
- `apps/backend/app/types/` — Money type not needed

**Stripped (single files):**
- `app/core/database.py`, `app/schemas/page.py`
- `pnpm-lock.yaml`, `pnpm-workspace.yaml`
- `.github/workflows/deploy.yml`, `.github/workflows/copilot-review.yml`
- Widget `_generated/` error classes, widget tests, DB-coupled tests, Money/Page/config-validator tests
- `packages/error-contracts/{src/, scripts/validate_translations.py, package.json, tests/test_validate_translations.py}`

**Stripped (subset deletions inside multi-purpose files):**
- HTTP middleware: kept only `RequestIdMiddleware`. Stripped access log, security headers, CORS.
- `.pre-commit-config.yaml`: stripped biome + vitest hooks
- `.github/dependabot.yml`: stripped npm × 2 + terraform ecosystems
- `.github/workflows/ci.yml`: stripped frontend-checks + api-client-checks jobs and the postgres service
- `Taskfile.yml`: stripped frontend / DB / Docker / Storybook tasks

**Stripped docs (template-internal, no longer relevant to a bootstrapped project):**
- `docs/reshape-plan.md` (template meta-history)
- `docs/new-project-setup.md` (project setup checklist for a fresh template clone)

**Rewritten:** `CLAUDE.md`, `README.md`, `.env.example`, all surviving `docs/*.md`,
`apps/backend/pyproject.toml`, `app/main.py`, `app/core/config.py`, `app/api/request_id_middleware.py`,
`app/api/health_router.py`, `architecture/import-linter-contracts.ini`, `errors.yaml`,
`Taskfile.yml`, `ci.yml`, `dependabot.yml`. `TEMPLATE_FRICTION.md` preserved with this
entry appended.

**Friction observed during bootstrap (feedback into future template improvements):**

- The template's HTTP middleware bundles four concerns (request_id, access log, security headers, CORS) into one `configure_middleware()` factory whose signature includes `cors_origins`. Stripping three of the four required rewriting the factory signature, which cascaded into a `main.py` edit. A per-middleware `add_X_middleware()` factory pattern would let projects opt in/out individually without changing the factory's call site.
- The `_generated/_registry.py` and `_generated/__init__.py` had to be hand-edited after deleting widget _generated/ files because `task errors:generate` couldn't run without first installing dependencies (chicken-and-egg with stripped pyproject.toml). Future bootstraps could skip the hand-edit by running `uv sync --dev && task errors:generate` immediately after `errors.yaml` is edited.
- `docs/automerge.md` is heavily template-flavored (frontend-checks references, pnpm lockfile examples). Most of its content is generic Dependabot mechanics that apply unchanged, but a project-specific scrub is needed. A header note + a few surgical edits got it acceptable for v1; a fuller rewrite would be cleaner.
- `docs/decisions.md` had four ADRs scoped to stripped capabilities (ADR-002 Pagination, ADR-006 i18n-from-day-one, ADR-007 Money, ADR-008 Biome+ESLint). Project-bootstrap stripped them rather than keeping them as historical decisions, on the grounds that ADRs document *current* decisions; historical decisions live in git history.
- The integration test `conftest.py` had Testcontainers + DB + widget references baked deeply into one file. A no-DB project could not preserve any part of it; the entire fixture file had to be rewritten into a 10-line ASGI-transport client fixture. A modular `conftest.py` (one module per fixture concern: `_db.py`, `_client.py`, `_auth.py`) would let projects keep relevant fixtures and strip the rest with targeted file deletions instead of rewriting from scratch.
