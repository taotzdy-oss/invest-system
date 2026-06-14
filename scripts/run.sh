#!/usr/bin/env bash
# 启动入口
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-8787}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[错误] 未找到 $PYTHON_BIN，请先安装 Python 3.9+"
  exit 1
fi

PY_VER=$("$PYTHON_BIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])')
echo "[启动] Python $PY_VER  端口 $PORT  根目录 $ROOT"
exec "$PYTHON_BIN" app.py --port "$PORT" "$@"
