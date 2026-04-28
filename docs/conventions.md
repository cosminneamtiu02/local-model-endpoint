# Conventions

Rules that govern how code is written in this repository. See `CLAUDE.md` for the
enforcement version. This document provides rationale.

## File Naming

| Context | Convention | Example |
|---|---|---|
| Python files | `snake_case.py` | `inference_service.py` |
| Python classes | `PascalCase` + role suffix | `InferenceService`, `OllamaRepository` |
| Python functions | `snake_case` verbs | `resolve_tag`, `merge_params` |
| Feature folders | `snake_case` | `features/inference/` (hyphens are not valid in Python package names) |

The model directory is `model/` (singular), not `models/` — it holds value-objects
for the feature, not a collection of ORM models.

## Spec graph

The requirements tree at `graphs/LIP/` is the source of truth for what
the project must build. Each node has a frontmatter status:

- `stub` — created by `requirements-elicitation`; one-line description.
- `detailed` — thickened by `feature-elicitation` with full sections.
- `verifiable` — test scenarios added by `test-generation`.
- `implemented` — feature is in code (set by hand once code lands).

Never write implementation before the corresponding feature reaches
`verifiable` status, and never bump to `implemented` without code +
tests + a passing `task check`.

## Test Naming

| Context | Convention | Example |
|---|---|---|
| Python | `test_<unit>_<scenario>_<expected>` | `test_inference_service_resolves_logical_name_to_tag` |

## Test File Location

- `tests/unit/` and `tests/integration/` mirror the source tree.
  `app/features/inference/service.py` -> `tests/unit/features/inference/test_inference_service.py`.
- `tests/contract/test_schemathesis.py` for OpenAPI contract validation.

## Pydantic Schemas

Each feature owns its wire schemas in `features/<name>/schemas/`. Common file roles:

- `<entity>_request.py` — fields the consumer sends.
- `<entity>_response.py` — fields the service returns.

Schemas may import value-objects from `model/` (Message, ModelParams, ContentPart,
ModelInfo, OllamaChatResult) — `model/` in LIP holds project value-objects, not ORM
types, since the service has no database. Models never import schemas; that direction
stays strict. See the Layer Rules in [CLAUDE.md](../CLAUDE.md) for the authoritative
statement.

Repositories cannot import from schemas (they are the data-access boundary). This
matches the import-linter contract `inference-repository-no-schemas` in
[apps/backend/architecture/import-linter-contracts.ini](../apps/backend/architecture/import-linter-contracts.ini).

## Error System

- Error codes defined in `packages/error-contracts/errors.yaml` (single source of truth).
- Codegen produces one file per error class in `exceptions/_generated/`.
- `task errors:generate` regenerates; `task check:errors` verifies committed files match.

## Dependencies

- Always use absolute latest versions.
- Close/delete Dependabot PRs that propose older versions.
- Every new dependency requires justification.

## Environment Variables

- All config via `pydantic-settings` in `core/config.py`.
- Every new env var added to both the `Settings` class and `.env.example` in the same commit.
