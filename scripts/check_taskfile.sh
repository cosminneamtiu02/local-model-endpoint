#!/usr/bin/env bash
# Validates Taskfile.yml syntax via `task --list-all`. Surfaces a friendlier
# error if Taskfile itself is not installed (the most common bootstrap
# stumble for fresh-clone developers).
set -euo pipefail

if ! command -v task >/dev/null 2>&1; then
    echo "ERROR: 'task' (Taskfile.dev) not found on PATH."
    echo "Install with: brew install go-task   (macOS)"
    echo "Or see https://taskfile.dev/installation/ for other platforms."
    exit 1
fi

task --list-all >/dev/null
