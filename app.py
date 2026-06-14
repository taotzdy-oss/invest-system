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
    args = parser.parse_args(argv)

    init_db()
    _validate_legacy()

    # 注册路由
    import modules  # noqa: F401

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
