#!/usr/bin/env bash
# Runs every CI check locally. Usage: scripts/check.sh [api|web]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
target="${1:-all}"

api() {
  echo "== API"
  cd "$ROOT/services/api"
  if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python; else PY=.venv/bin/python; fi
  "$PY" -m ruff check .
  "$PY" -m ruff format --check .
  "$PY" -m mypy app tests
  VERIXA_ENVIRONMENT=test "$PY" -m pytest -q
  tmp="$(mktemp -d)"
  VERIXA_ENVIRONMENT=test VERIXA_DATA_DIR="$tmp" "$PY" -m alembic upgrade head
  VERIXA_ENVIRONMENT=test VERIXA_DATA_DIR="$tmp" "$PY" -m alembic check
  rm -rf "$tmp"
}

web() {
  echo "== Web"
  cd "$ROOT"
  npm run lint
  npm run format:check
  npm run typecheck
  NEXT_TELEMETRY_DISABLED=1 npm run build
}

case "$target" in
  api) api ;;
  web) web ;;
  all) api; web ;;
  *) echo "unknown target: $target" >&2; exit 2 ;;
esac
echo "== All checks passed"
