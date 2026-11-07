#!/usr/bin/env bash
# One command for every Ralph story gate: syntax checks plus the offline tests. Safe to run any time.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

"$PY" -m py_compile scripts/*.py
for f in scripts/*.mjs scripts/lib/*.mjs; do [ -f "$f" ] && node --check "$f"; done
for f in scripts/*.sh ralph/*.sh; do [ -f "$f" ] && bash -n "$f"; done

if [ -d tests/py ]; then "$PY" -m pytest -q tests/py; fi
if [ -d tests/js ]; then node --test tests/js; fi
echo "check ok"
