# Architectural Decision Record

Decisions that shape this project. Each entry is final unless explicitly superseded.

> **Note on numbering.** ADRs 002, 006, 007, 008 were retired during the
> 2026-04-27 LIP bootstrap (template → LIP). See git history for the
> original full-stack-template decisions.

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

## ADR-005: Health at Root, Business at /v1/

**Status:** Accepted
**Date:** 2026-04-07

`/health` lives at the root, outside `/v1/`. Inference endpoints live under `/v1/`.
(Inference endpoints land via LIP-E001-F002.)

**Rationale:** Load balancers and orchestrators hardcode health paths. Versioning health
endpoints forces infrastructure config changes on API version bumps.

## ADR-009: Pre-commit Fast, Pre-push Unit Tests, CI Everything

**Status:** Accepted
**Date:** 2026-04-07

Pre-commit: ruff (lint + format), trailing-whitespace, end-of-file-fixer,
check-yaml/json, large-file guard, detect-secrets, Taskfile syntax check (~5-10s).
Pre-push: pyright, import-linter, unit tests.
CI: all three test levels (unit, integration, contract) + type checker + import-linter
+ error-contracts regen check.

**Rationale:** Fast commit loop. Tests before code leaves the machine. Full verification
before merge.

## ADR-010: Dependabot Auto-Merge Exception to Manual-Squash Rule

**Status:** Accepted (currently dormant — DEPENDABOT_AUTOMERGE_ENABLED not set)
**Date:** 2026-04-12

The "every merge uses the green Squash button manually" rule has exactly one exception:
Dependabot PRs that arrive green are automatically squash-merged when
`DEPENDABOT_AUTOMERGE_ENABLED='true'`. Every human or source-code PR still merges
exclusively via the manual Squash button.

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

## ADR-011: Per-Layer Scaffolding Deferred Until Feature Lands

**Status:** Accepted
**Date:** 2026-04-28

Feature subdirectories `service/` and `router/` (and any other layer not yet
backed by code) are not pre-scaffolded under `app/features/<feature>/`. They
appear only when a PR introduces them with the corresponding code, tests, and
import-linter contracts.

**Rationale:** Empty packages add noise without adding value. Import-linter
contracts that source from non-existent modules are no-ops, so the layer
contracts in `architecture/import-linter-contracts.ini` only assert on layers
that actually exist. The `task errors:generate` pattern already proves the
project tolerates partial scaffolds — error classes are codegen'd into
`_generated/` lazily as `errors.yaml` grows; the same lazy-fill discipline
applies to feature layers.

**Implication.** Reviewers should not expect to see `service/` or `router/`
directories before LIP-E001-F002 / LIP-E003-F002 lands them. The absence is
deliberate, not an oversight.

**Rejected:** Pre-scaffolding all four layers per feature with empty
`__init__.py` files. Adds dead surface area, makes "what exists" harder to
read at a glance, and tempts contributors to add stubs that drift from the
spec.

## ADR-012: Typed `AppState` Lifespan Container

**Status:** Accepted
**Date:** 2026-04-28

Lifespan-managed resources are stored in a typed `AppState` dataclass at
`app/api/app_state.py`, attached to the FastAPI app as `app.state.context`,
and read by `Depends` factories via `request.app.state.context.<field>`.

**Rationale.** Starlette's `app.state` accessor is `Any`-typed; reaching
through it directly leaks `Any` into every consumer and reduces Pyright
strict mode's value to "compiles, no guarantees about shape." Wrapping
the lifespan resources in a `@dataclass(slots=True)` gives Pyright a
single typed entry point and forbids dynamic attribute attachment
(`slots=True`) that would otherwise let `app.state.context.foo = bar`
silently grow into a service-locator pattern.

`Depends(get_app_state)` and `Depends(get_ollama_client)` factories in
`app/api/deps.py` are the only call sites that touch `app.state.context`;
route handlers stay pure (`async def handler(client = Depends(get_ollama_client))`)
without ever knowing the wrapper exists.

**Implication.** Adding a new lifespan-managed resource is a four-step
edit: append a field to `AppState`, construct it in `lifespan_resources`
(pairing it with its async-context-manager teardown), expose a `Depends`
factory in `deps.py`, and update consumers. No global registry, no
service-locator helpers, no module-level singletons — `Depends` does
the work.

**Rejected.**

- *Per-resource attribute on `app.state` directly* (`app.state.ollama_client = ...`).
  Untyped, drifts as features land, no `slots=True` discipline against
  ad-hoc additions. This is the shape PR #11 initially shipped with;
  the typed dataclass replaced it once a second resource was anticipated.
- *Pydantic model for AppState.* Validation overhead per access on
  objects holding open httpx clients adds cost without buying anything;
  the dataclass with slots gives the typing benefit without runtime cost.
- *Module-level singleton + `get_app_state()` factory.* Service-locator
  pattern, forbidden by CLAUDE.md, breaks per-test app isolation.


## ADR-013: OpenAPI `operation_id` Casing — camelCase

**Date:** 2026-05-03

**Status:** Accepted (round-7 review sweep — lane 11 follow-up).

**Context.** The single existing route (`GET /health`) declares
`operation_id="getHealth"` — camelCase. CLAUDE.md naming convention
("Python functions: `snake_case` verbs") covers Python identifiers,
not OpenAPI operation identifiers, so the casing decision was
unanchored. When LIP-E001-F002 adds the inference router, two options
exist for the next operation_id: `chat_completion` (snake_case,
matches the Python function name) or `chatCompletion` (camelCase,
matches every popular OpenAPI client-SDK generator's default
`operationName` convention).

**Decision.** Pin **camelCase** as the operation_id casing for every
route. Existing `getHealth` stays; future routes follow.

**Why.**
- Once consumers generate SDKs from `/openapi.json`, the operation
  becomes a method name on the generated client. `getHealth()` /
  `chatCompletion()` is the idiomatic call shape in JS / TS / Java /
  Go / Swift. Snake_case here would give consumers `get_health()` in
  every language, which only feels native in Python.
- camelCase is the de facto OpenAPI convention; OpenAPI
  Generator, NSwag, openapi-typescript-codegen all default to
  camelCase operation names regardless of source casing.
- The Python function name is a separate handle (`get_health`,
  `chat_completion`); the operation_id is the wire-contract handle.
  Matching them character-for-character was never a goal.

**Rejected alternatives.**
- *snake_case operation_id.* Aligns with the Python function name
  but produces non-idiomatic SDK method names for every non-Python
  consumer; LIP's consumer set today is multi-language (the
  consumer-side backends include Node and Python).
- *Leave undocumented.* The single-route status quo. A second route
  picked by drift instead of policy is exactly the "two ways to do
  each thing" CLAUDE.md sacred rule forbids.

**Mechanical pin.** When LIP-E001-F002 lands the inference router,
its FastAPI decorator MUST set `operation_id="chatCompletion"` (or
the equivalent camelCase for whatever the wire path is named). A
future contract test could assert every operation in the OpenAPI
schema matches `^[a-z][a-zA-Z0-9]*$`; deferred until the second
operation lands so the test has more than one input to verify.
Future routes inheriting this rule: LIP-E001-F002 chat-completion +
LIP-E006-F002 state-inspection set.
