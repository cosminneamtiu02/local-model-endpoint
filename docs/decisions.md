# Architectural Decision Record

Decisions that shape this project. Each entry is final unless explicitly superseded.

## ADR-001: Vertical Slices over Layered-by-Role

**Status:** Accepted
**Date:** 2026-04-07

Backend uses vertical feature slices. Each feature is a self-contained folder
(`features/<name>/`) with all its layers inside. Shared abstractions live outside
features in `core/`, `schemas/`, `exceptions/`.

**Rationale:** Scales to production. A senior dev sees domain boundaries immediately.
AI-assisted development benefits from one-folder-per-feature context. Adding or removing
a feature touches one folder.

**Rejected:** Layered-by-role (Django/Rails style). Doesn't scale past ~15 entities.
Related code scattered across 5+ folders.

## ADR-003: Generated Error Contracts

**Status:** Accepted
**Date:** 2026-04-07

All errors crossing the API boundary are defined in `packages/error-contracts/errors.yaml`.
A codegen script produces typed Python exception classes.

**Rationale:** One source of truth. Type safety end-to-end. Boring to extend (edit YAML,
run codegen).

**Rejected:** Hand-written error classes without codegen (drift risk). Flat untyped error
codes without parameter contracts (no type safety).

## ADR-004: One Class Per File

**Status:** Accepted
**Date:** 2026-04-07

Every Python class lives in its own file. No exceptions except generated code in
`_generated/` directories (one file per generated class).

**Rationale:** Grep-ability. AI-friendly. Prevents file bloat. Forces explicit imports.

## ADR-005: Health at Root, Business at /api/v1/

**Status:** Accepted
**Date:** 2026-04-07

`/health` lives at the root, outside `/api/v1/`. Inference endpoints live under `/api/v1/`.

**Rationale:** Load balancers and orchestrators hardcode health paths. Versioning health
endpoints forces infrastructure config changes on API version bumps.

## ADR-009: Pre-commit Fast, Pre-push Unit Tests, CI Everything

**Status:** Accepted
**Date:** 2026-04-07

Pre-commit: ruff, trailing-whitespace, check-yaml/json (~5-10s).
Pre-push: pytest unit (~5-15s).
CI: all three test levels (unit, integration, contract) + type checker + import-linter
+ error-contracts regen check.

**Rationale:** Fast commit loop. Tests before code leaves the machine. Full verification
before merge.

## ADR-010: Dependabot Auto-Merge Exception to Manual-Squash Rule

**Status:** Accepted
**Date:** 2026-04-12

The "every merge uses the green Squash button manually" rule has exactly one exception:
Dependabot PRs that arrive green may be auto-merged by a workflow. Every human or
source-code PR still merges exclusively via the manual Squash button.

The mechanism is [.github/workflows/dependabot-automerge.yml](../.github/workflows/dependabot-automerge.yml),
which runs on every `pull_request` event, short-circuits unless the PR's author is
`dependabot[bot]` and `vars.DEPENDABOT_AUTOMERGE_ENABLED == 'true'`, and calls
`gh pr merge --auto --squash`. GitHub's native auto-merge queue then merges each such PR
if and only if every required status check on the `main-protection` ruleset is green and
every conversation is resolved — the exact same gates a human faces when clicking the
button.

**Guard condition — the PR author, not `github.actor`.** The workflow's `if:` reads
`github.event.pull_request.user.login`, not `github.actor`. `github.actor` is whoever
triggered the current event — when a human clicks "Update branch" in the UI on a
Dependabot PR, `github.actor` becomes that human and a condition based on it would
skip the job on every human-triggered sync. The PR author from the event payload stays
`dependabot[bot]` for the lifetime of the PR regardless of which individual event is
being processed, so it is the correct field to scope the exception on.

**Safety precondition — the ruleset is load-bearing.** `gh pr merge --auto` waits only
for the checks the ruleset declares required. If no ruleset exists, or the ruleset has
no required status checks, `--auto` has nothing to wait for and merges immediately
regardless of CI state — including merging a PR with failing checks. To prevent this,
the workflow is gated on the `DEPENDABOT_AUTOMERGE_ENABLED` repo variable. The variable
must be set to `"true"` only after the `main-protection` ruleset has been created with
all required status checks. Until then, the workflow's `if:` evaluates false and the job
is a no-op. The variable also serves as the emergency kill switch.

**Rationale:** The invariant the project cares about is "main is always green," not
"a human physically clicked the button." Dependabot PRs are the highest-volume,
lowest-novelty PRs in the system: one package bump, no source logic change, validated
by the same required checks every other PR faces. Requiring a human to manually squash
each adds latency without adding safety — the safety already lives in the ruleset.
Automating the click lets the project absorb weekly dependency updates without
accumulating a backlog of green-but-unclicked PRs, which is the failure mode that breaks
the "always green" invariant in practice.
