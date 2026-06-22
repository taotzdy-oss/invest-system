#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人投资管理系统 - 启动入口。

用法:
    python3 app.py                 # 用 config.json 的端口
    python3 app.py --port 9000     # 临时覆盖端口
    python3 app.py --no-browser    # 不自动打开浏览器
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser

from core.config import CONFIG
from core.db import init_db
from core.router import run_server
from core.jobs import start_scheduler, run_job


def _validate_legacy() -> None:
    """启动时检查旧项目根目录是否存在；不存在则给警告但不阻塞启动。"""
    root = CONFIG.legacy_root
    if not root.exists():
        print(f"[警告] 旧项目根目录不存在：{root}")
        print(f"[警告] 你可以编辑 config.json 修改 legacy_root，或忽略此提示先进入系统。")
        return
    # 关键路径检查（缺失只警告）
    for key in ("knowledge_base_dir", "review_root"):
        p = CONFIG.legacy_path(key)
        if not p.exists():
            print(f"[警告] {key} 路径缺失：{p}")


def _open_browser_later(url: str, delay: float = 1.0) -> None:
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="个人投资管理系统")
    parser.add_argument("--host", default=CONFIG.server.get("host", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=CONFIG.server.get("port", 8787))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-scheduler", action="store_true",
                        help="禁用后台调度器（仅启动 Web）")
    parser.add_argument("--run-once", help="单次运行某任务后退出，例 --run-once health_check")
    args = parser.parse_args(argv)

    init_db()
    _validate_legacy()

    # 注册路由
    import modules  # noqa: F401

    # 单次跑模式
    if args.run_once:
        result = run_job(args.run_once)
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "ok" else 2

    # 启动后台调度器
    if not args.no_scheduler:
        try:
            start_scheduler()
            print(f"[调度] 已启动；任务定义见 /system 与 /#health")
        except Exception as e:
            print(f"[警告] 调度器启动失败：{e}")

    # 启动时跑一次 health_check + 同步，让首页立刻有最新数据
    try:
        run_job("backfill_sync")
        run_job("health_check")
    except Exception as e:
        print(f"[警告] 启动同步失败：{e}")

    if not args.no_browser and CONFIG.server.get("open_browser", True):
        _open_browser_later(f"http://{args.host}:{args.port}")

    try:
        run_server(args.host, args.port)
    except OSError as e:
        print(f"[错误] 端口启动失败：{e}")
        print(f"[提示] 可尝试 python3 app.py --port 8788 切换端口")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
