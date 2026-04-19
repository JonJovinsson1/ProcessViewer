#!/bin/bash
# Test runner for Programmer Process Viewer.
#
# Usage:
#   ./test.sh              → unit + TUI integration tests (fast, default)
#   ./test.sh --fuzz       → also run fuzz/soak tests
#   ./test.sh --only-fuzz  → fuzz/soak tests only
#   ./test.sh -k pattern   → pytest -k passthrough (any extra args go to pytest)
set -euo pipefail
cd "$(dirname "$0")"

VENV_PY="./.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
    echo "error: venv not found at .venv/. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest pytest-asyncio" >&2
    exit 1
fi

MODE="default"
EXTRA=()
for arg in "$@"; do
    case "$arg" in
        --fuzz)      MODE="all" ;;
        --only-fuzz) MODE="fuzz" ;;
        *)           EXTRA+=("$arg") ;;
    esac
done

case "$MODE" in
    default)
        echo "==> Running unit + TUI tests (excluding fuzz)"
        exec "$VENV_PY" -m pytest -m "not fuzz" ${EXTRA[@]+"${EXTRA[@]}"}
        ;;
    all)
        echo "==> Running full suite including fuzz/soak"
        exec "$VENV_PY" -m pytest ${EXTRA[@]+"${EXTRA[@]}"}
        ;;
    fuzz)
        echo "==> Running fuzz/soak tests only"
        exec "$VENV_PY" -m pytest -m fuzz ${EXTRA[@]+"${EXTRA[@]}"}
        ;;
esac
