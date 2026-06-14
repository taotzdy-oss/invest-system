"""端到端冒烟测试：
- 启动后台 server
- GET 所有关键路由，断言 200/302
- POST 一些写操作
- 关闭 server

仅依赖标准库。在终端 `python3 tests/smoke.py` 即可。
"""
from __future__ import annotations

import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import CONFIG  # noqa: E402
from core.db import init_db  # noqa: E402
from core.router import run_server  # noqa: E402
import modules  # noqa: F401,E402


HOST = "127.0.0.1"
PORT = 9911  # 用专门端口避免与正常运行冲突
BASE = f"http://{HOST}:{PORT}"


def _get(path: str, expect=(200,), follow_redirect=True) -> tuple[int, str]:
    try:
        url = BASE + urllib.parse.quote(path, safe="/?&=#")
        if follow_redirect:
            with urllib.request.urlopen(url, timeout=10) as r:
                body = r.read().decode("utf-8", errors="replace")
                return r.status, body
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(url, timeout=10) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _post(path: str, data: dict, expect=(200, 302)) -> tuple[int, str]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    url = BASE + urllib.parse.quote(path, safe="/?&=#")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    # 关闭自动跟随，否则 302 -> 200 拿不到原始状态码
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _check(label: str, status: int, body: str, ok=(200,), needles=()):
    color_ok, color_bad, reset = "\033[32m", "\033[31m", "\033[0m"
    success = status in ok
    if needles:
        for n in needles:
            if n not in body:
                success = False
                break
    flag = f"{color_ok}OK {reset}" if success else f"{color_bad}FAIL{reset}"
    print(f"[{flag}] {label}  status={status}")
    if not success:
        print(body[:400])
    return success


def main() -> int:
    init_db()
    server_started = threading.Event()

    def _serve():
        # 直接启 server；用守护线程，主测试结束自动退出
        from http.server import ThreadingHTTPServer
        from core.router import Handler
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
        server_started.set()
        try:
            srv.serve_forever()
        finally:
            srv.server_close()

    th = threading.Thread(target=_serve, daemon=True)
    th.start()
    server_started.wait(timeout=5)
    time.sleep(0.3)  # 等绑定完成

    failures = 0

    def expect(label, status, body, ok=(200,), needles=()):
        nonlocal failures
        if not _check(label, status, body, ok, needles):
            failures += 1

    # ---- GET 路由 ----
    s, b = _get("/")
    expect("GET /", s, b, needles=["总览"])

    s, b = _get("/strategy")
    expect("GET /strategy", s, b, needles=["策略管理"])

    scripts = []
    try:
        from adapters.strategy import list_strategy_scripts
        scripts = list_strategy_scripts()
        if scripts:
            s, b = _get(f"/strategy/script/{scripts[0].name}")
            expect("GET /strategy/script/<name>", s, b, needles=[scripts[0].name])
    except Exception as e:
        print(f"[FAIL] /strategy/script: {e}")
        failures += 1

    s, b = _get("/picks")
    expect("GET /picks", s, b, needles=["每日选股"])

    try:
        from adapters.stock_pick import list_pools
        pools = list_pools()
        if pools:
            s, b = _get(f"/picks/{pools[0].date}")
            expect("GET /picks/<date>", s, b, needles=[pools[0].iso_date])
    except Exception as e:
        print(f"[FAIL] /picks/<date>: {e}")
        failures += 1

    s, b = _get("/review")
    expect("GET /review", s, b, needles=["复盘管理"])

    s, b = _get("/review/ledger")
    expect("GET /review/ledger", s, b, needles=["复盘台账"])

    s, b = _get("/review/bucket/成功晋级池")
    expect("GET /review/bucket/<name>", s, b, needles=["成功晋级池"])

    s, b = _get("/review/experience")
    expect("GET /review/experience", s, b, needles=["复盘经验库"])

    s, b = _get("/review/iteration")
    expect("GET /review/iteration", s, b, needles=["策略迭代日志"])

    s, b = _get("/review/template")
    expect("GET /review/template", s, b, needles=["复盘模板"])

    try:
        from adapters.review import list_review_days
        days = list_review_days()
        if days:
            s, b = _get(f"/review/{days[0].date}")
            expect("GET /review/<date>", s, b, needles=[days[0].iso_date])
    except Exception as e:
        print(f"[FAIL] /review/<date>: {e}")
        failures += 1

    s, b = _get("/kb")
    expect("GET /kb", s, b, needles=["知识库"])

    s, b = _get("/kb?q=爆点")
    expect("GET /kb?q=", s, b, needles=["搜索"])

    s, b = _get("/system/logs")
    expect("GET /system/logs", s, b, needles=["运行日志"])

    # ---- POST 写操作 ----
    if scripts:
        s, b = _post("/strategy/snapshot", {"script": scripts[0].name, "label": "smoke-v1", "note": "smoke"})
        expect("POST /strategy/snapshot", s, b, ok=(302,))

    s, b = _get("/strategy/backtest/run", follow_redirect=False)
    expect("GET /strategy/backtest/run", s, b, ok=(302,))

    # 新增 / 删除 知识笔记
    s, b = _post("/kb/note", {"title": "smoke-note", "body": "# hi\nthis is a test", "tags": "smoke", "refs": ""})
    expect("POST /kb/note", s, b, ok=(302,))

    # 找回刚创建的 id
    from core.db import get_conn
    conn = get_conn()
    note = conn.execute("SELECT id FROM kb_notes WHERE title='smoke-note' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if note:
        s, b = _get(f"/kb/note/{note['id']}")
        expect("GET /kb/note/<id>", s, b, needles=["smoke-note"])
        s, b = _post(f"/kb/note/{note['id']}/delete", {})
        expect("POST /kb/note/<id>/delete", s, b, ok=(302,))

    # 复盘笔记
    try:
        from adapters.review import list_review_days
        days = list_review_days()
        if days:
            s, b = _post(f"/review/{days[0].date}/note", {"note": "smoke 测试笔记", "tags": "smoke"})
            expect("POST /review/<date>/note", s, b, ok=(302,))
    except Exception as e:
        print(f"[FAIL] review note post: {e}")
        failures += 1

    # 选股标记
    try:
        from adapters.stock_pick import list_pools
        pools = list_pools()
        if pools:
            s, b = _post(f"/picks/{pools[0].date}/mark",
                        {"code": "999999", "name": "测试", "mark": "watch", "note": "smoke"})
            expect("POST /picks/<date>/mark", s, b, ok=(302,))
    except Exception as e:
        print(f"[FAIL] picks mark post: {e}")
        failures += 1

    # ---- 静态文件 ----
    s, b = _get("/static/css/app.css")
    expect("GET /static/css/app.css", s, b, needles=["topbar"])

    print()
    if failures == 0:
        print("\033[32m✓ ALL SMOKE TESTS PASSED\033[0m")
        return 0
    print(f"\033[31m✗ {failures} CHECKS FAILED\033[0m")
    return 1


if __name__ == "__main__":
    sys.exit(main())
