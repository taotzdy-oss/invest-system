#!/usr/bin/env bash
# 卸载 launchd 任务
set -euo pipefail

PLIST_DST="$HOME/Library/LaunchAgents/com.local.invest.app.plist"
if [[ -f "$PLIST_DST" ]]; then
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  rm -fv "$PLIST_DST"
  echo "✅ 已卸载 com.local.invest.app"
else
  echo "未找到 $PLIST_DST"
fi
