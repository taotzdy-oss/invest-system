"""V2 端到端冒烟：
- 启动 server
- 6 段 dashboard / system / 各原模块路由全部 200
- /api/dashboard.json 关键字段
- 数据一致性：DB plans 数 ?= 磁盘观察池目录数
- jobs run 接口
- 各 job 单独 runnable 且 idempotent
"""
from __future__ import annotations

import json
import os
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
from core.db import init_db, get_conn  # noqa: E402
from core.router import run_server, Handler  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402
import modules  # noqa: F401,E402


HOST = "127.0.0.1"
PORT = 9913
BASE = f"http://{HOST}:{PORT}"


def _q(s: str) -> str:
    return urllib.parse.quote(s, safe="/?&=#")


def _get(path: str, follow=True):
    try:
        url = BASE + _q(path)
        if follow:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.status, r.read().decode("utf-8", errors="replace")
        class _NoR(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw): return None
        opener = urllib.request.build_opener(_NoR())
        with opener.open(url, timeout=10) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _post(path, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    url = BASE + _q(path)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    class _NoR(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw): return None
    opener = urllib.request.build_opener(_NoR())
    try:
        with opener.open(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


_PASS = "\033[32mOK\033[0m"
_FAIL = "\033[31mFAIL\033[0m"


def expect(label, cond, msg=""):
    print(f"[{_PASS if cond else _FAIL}] {label}  {msg if not cond else ''}")
    return bool(cond)


def main():
    init_db()
    started = threading.Event()
    def _serve():
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
        started.set()
        srv.serve_forever()
    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    started.wait(5)
    time.sleep(0.3)

    fails = 0

    # ---- 主页 6 段 ----
    s, b = _get("/")
    if not expect("GET / status", s == 200): fails += 1
    for tag in ("① 今日总览", "② 明日计划", "③ 当日复盘", "④ 趋势分析", "⑤ 策略迭代", "⑥ 系统健康"):
        if not expect(f"含 {tag}", tag in b): fails += 1

    # ---- API ----
    s, b = _get("/api/dashboard.json")
    if not expect("GET /api/dashboard.json", s == 200): fails += 1
    if s == 200:
        d = json.loads(b)
        for k in ("today", "tomorrow", "review", "trend", "iteration", "health"):
            if not expect(f"api.keys.{k}", k in d): fails += 1

    # ---- 子页面 ----
    for path in ("/system", "/strategy", "/picks", "/review", "/kb",
                 "/review/ledger", "/review/experience", "/review/iteration",
                 "/system/oss/new", "/system/improvement/new"):
        s, b = _get(path)
        if not expect(f"GET {path}", s == 200): fails += 1

    # ---- POST run job ----
    s, b = _post("/jobs/run/health_check", {})
    if not expect("POST /jobs/run/health_check", s == 302): fails += 1

    # ---- 数据一致性 ----
    conn = get_conn()
    try:
        db_plans = conn.execute("SELECT COUNT(*) c FROM plans").fetchone()["c"]
        db_reviews = conn.execute("SELECT COUNT(*) c FROM reviews").fetchone()["c"]
        db_ledger = conn.execute("SELECT COUNT(*) c FROM review_results").fetchone()["c"]
        db_premium = conn.execute("SELECT COUNT(*) c FROM premium_tracking").fetchone()["c"]
    finally:
        conn.close()
    from adapters import stock_pick, review as rv
    file_pools = len(stock_pick.list_pools())
    file_reviews = len(rv.list_review_days())
    file_ledger = len(rv.ledger_rows())
    file_premium = len(rv.premium_rows())
    if not expect(f"plans = pools ({db_plans}={file_pools})", db_plans == file_pools): fails += 1
    if not expect(f"reviews = review_days ({db_reviews}={file_reviews})", db_reviews == file_reviews): fails += 1
    if not expect(f"ledger DB >= file ({db_ledger}>={file_ledger})", db_ledger >= file_ledger): fails += 1
    if not expect(f"premium DB = file ({db_premium}={file_premium})", db_premium == file_premium): fails += 1

    # ---- job idempotency ----
    from core.jobs import run_job
    r1 = run_job("backfill_sync")
    r2 = run_job("backfill_sync")
    if not expect("backfill_sync 2x ok", r1["status"] == "ok" and r2["status"] == "ok"): fails += 1
    # 重跑次数后行数不应改变（plans/reviews/ledger/premium 计数稳定）
    conn = get_conn()
    try:
        plans_after = conn.execute("SELECT COUNT(*) c FROM plans").fetchone()["c"]
        reviews_after = conn.execute("SELECT COUNT(*) c FROM reviews").fetchone()["c"]
        ledger_after = conn.execute("SELECT COUNT(*) c FROM review_results").fetchone()["c"]
    finally:
        conn.close()
    if not expect(f"idempotent plans ({db_plans}={plans_after})", db_plans == plans_after): fails += 1
    if not expect(f"idempotent reviews ({db_reviews}={reviews_after})", db_reviews == reviews_after): fails += 1
    if not expect(f"idempotent ledger ({db_ledger}={ledger_after})", db_ledger == ledger_after): fails += 1

    # ---- CSV 校验 ----
    from core.health import check_csv_format
    pools = stock_pick.list_pools()
    bad = 0
    for p in pools[:5]:
        for i in check_csv_format(p):
            if i["severity"] == "error":
                bad += 1
    if not expect(f"latest 5 pools CSV no error ({bad}=0)", bad == 0): fails += 1

    print()
    if fails == 0:
        print(f"\033[32m✓ ALL V2 SMOKE PASSED\033[0m")
        return 0
    print(f"\033[31m✗ {fails} CHECK(S) FAILED\033[0m")
    return 1


if __name__ == "__main__":
    sys.exit(main())
