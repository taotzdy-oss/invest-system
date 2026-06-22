#!/bin/zsh
# 双击启动本系统（在用户登录会话内运行，可访问 ~/Desktop）。
# 系统启动后自动在浏览器打开 http://127.0.0.1:8787

cd "$(dirname "$0")"
export TZ=Asia/Shanghai
export LANG=zh_CN.UTF-8

# 占用端口的旧进程先停掉（如果是本系统的）
EXIST_PID=$(lsof -nP -iTCP:8787 -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $2}')
if [[ -n "$EXIST_PID" ]]; then
  echo "[启动] 检测到端口 8787 被 PID $EXIST_PID 占用，将先杀掉。"
  kill "$EXIST_PID" 2>/dev/null
  sleep 1
fi

echo "[启动] 投资管理系统..."
/usr/bin/python3 app.py
