# Architectural Decision Record

Decisions that shape this project. Each entry is final unless explicitly superseded.

> **Note on numbering.** ADRs 002, 006, 007, 008 were retired during the
> 2026-04-27 LIP bootstrap (template → LIP). See
> [docs/bootstrap-decisions.md](bootstrap-decisions.md) for the curated
> rationale (retired ADRs documented in the "Decision log" table) or git
> history for the original full-stack-template decisions.

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
(LIP-E001-F002 lands the inference endpoint; LIP-E006-F002 lands the
state-inspection set; both under `/v1/`.)

**Rationale:** Load balancers and orchestrators hardcode health paths. Versioning health
endpoints forces infrastructure config changes on API version bumps.

## ADR-009: Pre-commit Fast, Pre-push Unit-Only, CI Everything

**Status:** Accepted (revised 2026-05-04 to match the round-14 lane 10.6
narrowing of the pre-push stage)
**Date:** 2026-04-07

Pre-commit: ruff (lint + format), trailing-whitespace, end-of-file-fixer,
check-yaml/json, large-file guard, detect-secrets, Taskfile syntax check (~5-10s).
Pre-push: backend unit tests + error-contracts unit tests only.
CI: all three backend test levels (unit, integration, contract) + type checker +
import-linter + error-contracts codegen+regen + pip-audit + secret scan.

**Rationale:** Fast commit loop. Unit tests before code leaves the machine. The
slower pyright/import-linter/integration/contract checks live in CI only — running
them at pre-push too created real pressure to use `--no-verify` (which CLAUDE.md
forbids), since `main-protection` already gates merges on the same checks. Operators
wanting the full local mirror still have `task check` as the sacred-rule entry point.

## ADR-010: Dependabot Auto-Merge Exception to Manual-Squash Rule

**Status:** Accepted (live — `DEPENDABOT_AUTOMERGE_ENABLED='true'` since 2026-04-27)
**Date:** 2026-04-12

The "every merge uses the green Squash button manually" rule has exactly one exception:
Dependabot PRs that arrive green are automatically squash-merged when
`DEPENDABOT_AUTOMERGE_ENABLED='true'`. Every human or source-code PR still merges
exclusively via the manual Squash button.

The mechanism is [.github/workflows/dependabot-automerge.yml](../.github/workflows/dependabot-automerge.yml),
which runs on every `pull_request` open / synchronize / reopen event, short-circuits
unless the PR's author is `dependabot[bot]` and `vars.DEPENDABOT_AUTOMERGE_ENABLED == 'true'`,
and calls `gh pr merge --auto --squash`. GitHub's native auto-merge queue then merges each such PR
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
was flipped to `"true"` on 2026-04-27 once the `main-protection` ruleset existed with
all three required status checks (`backend-checks`, `error-contracts`, `darwin-checks`)
configured. The variable also serves as the emergency kill switch — flipping it back to
`"false"` disables the auto-merge stack cleanly without touching the workflow itself.

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
the lifespan resources in a `@dataclass(slots=True, frozen=True)` gives
Pyright a single typed entry point and forbids dynamic attribute
attachment (`slots=True`) that would otherwise let
`app.state.context.foo = bar` silently grow into a service-locator
pattern. `frozen=True` then forbids in-place mutation of the existing
fields after construction, so a lifespan-managed httpx client cannot be
silently swapped mid-request.

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

**Status:** Accepted

**Date:** 2026-05-03

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


## ADR-014: Unknown `LIP_*` Env Vars — Warn-and-Continue, Not Hard-Fail

**Status:** Accepted

**Date:** 2026-05-04

**Context.** `pydantic-settings` 2.14 silently ignores unknown env
vars at the env-source layer (its `extra="forbid"` only fires on init
kwargs). To surface operator typos like `LIP_OLLMA_HOST=...`, LIP
runs an `audit_lip_env_typos()` audit at startup that enumerates
`os.environ` and warns about any `LIP_*` name that doesn't match a
declared `Settings` field. Today the warning is informational —
`logger.warning("unknown_lip_env_vars_ignored", env_vars=...)` — and
the app boots with default values for the typo'd field. Round 14's
review-sweep lane 19.6 raised the question of whether the audit
should instead `raise RuntimeError` so a typo blocks deploy.

**Decision.** Keep the **warn-and-continue** behavior. Do not
escalate to a boot-blocking failure.

**Why.**
- LIP is a single-developer LAN service. The typo-catch loop is
  short: an operator running `task dev` sees the `unknown_lip_env_vars_ignored`
  warning in stdout on the first boot and fixes the typo. There is no
  multi-tenant production CI/CD pipeline where the warning would be
  buried under unrelated traffic.
- Hard-failing boot on env-var validity removes operational
  flexibility for legitimate transient overrides — staged rollouts of
  new env vars (set on the operator shell before the corresponding
  `Settings` field is added so a service restart doesn't lose the
  intent), debugging shims (`LIP_DEBUG_FOO=1` set ad-hoc to gate a
  manual inspection), and bisection (one operator can run multiple
  LIP instances on the same machine with experimental env vars
  without rebuilding the Settings class for each).
- Boot-time hard-fail enlarges the deploy-failure surface. Today
  `task dev` boots even on a misconfigured env; the operator gets
  one warning line and chooses whether to act. Hard-fail trades
  that observability for a process-exit code that masks the same
  signal under "the daemon won't start."
- The warning is the symmetric pair of pydantic-settings's typed
  field validation: typed fields fail at construction (right
  default), unknown extras warn at startup (right default for the
  unknown-by-construction case). The two failure modes match the
  underlying epistemic difference — known shape vs unknown shape.

**Rejected alternatives.**
- *Hard-fail boot via `raise RuntimeError("unknown LIP_* env vars: ...")`.*
  Catches operator typos before traffic, but trades the flexibility
  cases above for marginal protection. The current warning already
  fires on the first boot the operator runs, so the "before traffic"
  property holds in practice for the single-developer model.
- *Hard-fail in production, warn in development.* Adds a second way
  to do one thing (CLAUDE.md sacred rule #3) and would couple env-var
  policy to `LIP_APP_ENV` — a cross-concern surface that the audit
  helper is intentionally independent of.
- *Skip the audit entirely.* The pydantic-settings silent-ignore
  surface is real; without the audit, a typo would deploy with
  default values and the only signal would be unexpected runtime
  behavior. Worse than the warning.

**Mechanical pin.** `audit_lip_env_typos()` in `app/api/deps.py`
emits at warning level and never raises. The unit tests at
`tests/unit/api/test_deps.py::test_audit_lip_env_typos_*`
(`warns_on_unknown_lip_env_var`, `does_not_warn_when_all_env_vars_known`,
`catches_lowercase_typo`, `no_ops_when_env_prefix_empty`,
`de_dups_case_variants`) pin the warn-only contract together. A future
change of mind on this ADR needs to flip both sites in lockstep AND
update all five tests to assert the raise path.
