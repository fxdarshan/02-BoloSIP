#!/usr/bin/env sh
# Run every BoloSIP check: unit tests, then the evaluation gates.
# Usage (from anywhere):  sh scripts/check.sh
set -e
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

echo "== Unit tests"
"$PY" -m unittest discover tests

echo "== Evaluation gates"
"$PY" -m eval.run --all --no-write

echo "All checks passed."
