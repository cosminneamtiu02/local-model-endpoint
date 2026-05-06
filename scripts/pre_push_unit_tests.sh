#!/usr/bin/env bash
# Pre-push fast-safety-net: unit tests for both workspaces.
#
# Extracted from .pre-commit-config.yaml's chained ``bash -c "...cd
# apps/backend && ... && cd ../../packages/error-contracts && ..."``
# inline so a future repo-restructure that changes the workspace layout
# is a one-file edit (here) rather than a fragile inline shell scrub.
# Pre-commit invokes pre-push hooks from the repo root per its contract,
# so the relative ``apps/backend`` / ``packages/error-contracts`` paths
# below are stable.
#
# Tier scope per CLAUDE.md / .pre-commit-config.yaml lane 10.6: unit
# tests only. Integration, contract, types, and import-linter are
# the authoritative CI gate; running them locally here would just
# duplicate seconds-later CI and pressure ``--no-verify`` use.
# Operators wanting the full local mirror have ``task check``.
set -euo pipefail

uv run --frozen --directory apps/backend pytest tests/unit/ -q
uv run --frozen --directory packages/error-contracts pytest tests/ -q
