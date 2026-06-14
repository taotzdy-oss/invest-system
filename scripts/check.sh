#!/usr/bin/env bash
# 一键自检：跑单测 + 烟雾测试
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "==> 单元测试"
"$PYTHON_BIN" tests/test_units.py
echo ""
echo "==> 端到端冒烟测试"
"$PYTHON_BIN" tests/smoke.py
