#!/usr/bin/env bash
# 安装 launchd 任务：开机自启 + 进程退出自动重启
# 使用：bash scripts/launchd/install.sh
set -euo pipefail

PLIST_SRC="/Users/gegezi/Desktop/投资管理系统/scripts/launchd/com.local.invest.app.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.local.invest.app.plist"

mkdir -p "$HOME/Library/LaunchAgents"
cp -v "$PLIST_SRC" "$PLIST_DST"

# 卸载老的 (容错)
launchctl unload "$PLIST_DST" 2>/dev/null || true

launchctl load "$PLIST_DST"
echo ""
echo "✅ 已注册 launchd 服务 com.local.invest.app"
echo "   下次开机会自动启动；进程异常退出后 15s 内自动重启"
echo ""
echo "查看状态: launchctl list | grep invest"
echo "查看日志: tail -f /Users/gegezi/Desktop/投资管理系统/data/app.log"
echo "卸载:     bash scripts/launchd/uninstall.sh"
