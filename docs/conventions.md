# Conventions

Rules that govern how code is written in this repository. See `CLAUDE.md` for the
enforcement version. This document provides rationale.

## File Naming

| Context | Convention | Example |
|---|---|---|
| Python files | `snake_case.py` | `inference_service.py` |
| Python classes | `PascalCase` + role suffix | `InferenceService`, `OllamaRepository` |
| Python functions | `snake_case` verbs | `resolve_tag`, `merge_params` |
| Feature folders | `kebab-case` | `features/inference/` |

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
