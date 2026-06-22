"""自动任务系统（线程内调度，单进程，标准库实现）。

Jobs（与 SKILL.md 约定一致）:

| name              | when (Asia/Shanghai)    | what                                           |
|-------------------|-------------------------|------------------------------------------------|
| ladder_refresh    | weekdays 15:30 / 17:00  | 重建连板天梯统计                                |
| review_daily      | weekdays 16:00          | 跑当日复盘                                      |
| picks_daily       | weekdays 18:00          | 跑下一交易日选股                                 |
| backfill_sync     | hourly (light)          | 重新从磁盘同步旧项目数据进 DB                    |
| health_check      | every 10 min            | 数据新鲜度 / CSV 校验 / 任务漏跑补偿             |

调度策略：
- 每分钟 tick 一次
- 命中条件 = (任务启用) AND (当前时间 >= scheduled) AND (当天该任务还未跑/上次失败)
- 任务跑前先取"任务锁"，避免并发；跑完释放
- 所有"调用旧项目 .py 脚本"的任务，通过 adapters.runner.run_python 落 run_logs
- 任务结果同步落 job_runs，并更新 jobs.last_*

注意：
- ladder_refresh / review_daily / picks_daily 真正执行的是旧项目脚本（reuse），
  本系统只负责调度与状态展示，绝不在程序内编造行情。
- 旧项目脚本如果不存在/可执行性问题，会标 health_issues 并跳过。
"""
from __future__ import annotations

import datetime as _dt
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from adapters import stock_pick as sp_adapter
from adapters.runner import run_python
from core.calendar import (
    confirmed_trading_days, is_confirmed_trading_day, latest_trading_day,
    next_trading_day,
)
from core.clock import TZ, fmt_now, now, today_iso
from core.config import CONFIG
from core.db import get_conn, tx


# --- 任务定义 ---------------------------------------------------------------

@dataclass
class JobSpec:
    name: str
    cron_hint: str        # 文本描述
    schedule_minute: int  # 当日触发到达此分钟数（如 16:00 = 16*60+0）
    end_minute: int       # 容错窗口截止
    weekday_only: bool
    runner: str           # 函数名
    description: str


JOBS: list[JobSpec] = [
    JobSpec("ladder_refresh", "工作日 15:30 / 17:00", 15 * 60 + 30, 17 * 60 + 30,
            True, "run_ladder_refresh", "重建连板天梯统计"),
    JobSpec("review_daily", "工作日 16:00", 16 * 60, 23 * 60 + 59,
            True, "run_review_daily", "跑当日复盘（基于真实数据，调用 review skill）"),
    JobSpec("picks_daily", "工作日 18:00", 18 * 60, 23 * 60 + 59,
            True, "run_picks_daily", "生成下一交易日观察池（调用最新 generate 脚本或新写）"),
    JobSpec("backfill_sync", "每小时", -1, -1, False, "run_backfill_sync",
            "把旧项目目录的新增数据同步进 DB"),
    JobSpec("health_check", "每 10 分钟", -1, -1, False, "run_health_check",
            "数据新鲜度 + CSV 校验 + 任务漏跑补偿"),
]


# --- 锁 ---------------------------------------------------------------------

_LOCK_DIR = Path(__file__).resolve().parent.parent / "data" / "locks"


def _lock_path(name: str) -> Path:
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    return _LOCK_DIR / f"{name}.lock"


def acquire_lock(name: str) -> bool:
    p = _lock_path(name)
    if p.exists():
        # 自动清理超时锁（>60min）
        age = time.time() - p.stat().st_mtime
        if age > 3600:
            p.unlink(missing_ok=True)
        else:
            return False
    p.write_text(f"{fmt_now()}\n{os_pid()}\n")
    return True


def release_lock(name: str) -> None:
    _lock_path(name).unlink(missing_ok=True)


def os_pid() -> int:
    import os
    return os.getpid()


# --- 任务实现 ---------------------------------------------------------------

def run_ladder_refresh(target_date: str | None = None) -> dict:
    """运行 ladder 脚本，刷新连板天梯数据。"""
    # 旧项目里没有显式 ladder refresh 脚本（数据通过其它流程生成）。
    # 我们做的是：把磁盘最新数据再次回填进 DB，并检查 errors。
    from core.backfill import backfill_ladder
    n = backfill_ladder()
    meta_path = CONFIG.legacy_path("ladder_data_dir") / "连板天梯_meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    return {"rows": n, "meta": meta, "note": "依赖旧脚本生成的 ladder CSV；本任务只做导入与新鲜度检查。"}


def run_review_daily(target_date: str | None = None) -> dict:
    """跑当日复盘。

    实施约束：
    - target_date 默认是"今天的最近交易日"
    - 旧项目的复盘是手工/skill 触发，没有单一 Python 脚本可一键运行
    - 我们做的是：检测当日复盘报告文件是否存在；若已存在 -> 把数据 sync 到 DB；
      若不存在 -> 标 health_issue "review_missing"，提示需要人工 / skill 复盘
    """
    iso = target_date or latest_trading_day(today_iso())
    if not is_confirmed_trading_day(iso):
        return {"skipped": True, "reason": f"{iso} 不是已确认交易日"}

    compact = iso.replace("-", "")
    report_path = (CONFIG.legacy_path("review_daily_dir") / compact /
                   f"锋芒爆点_{compact}_复盘报告.md")
    if not report_path.exists():
        with tx() as conn:
            conn.execute(
                "INSERT INTO health_issues (severity, kind, target, detail) VALUES (?,?,?,?)",
                ("warn", "review_missing", iso,
                 f"未发现 {report_path}（请按 review skill 手动/自动跑复盘后此任务会再次刷新）"),
            )
        return {"target_date": iso, "ok": False, "blocked": "report_missing",
                "expected_path": str(report_path)}

    from core.backfill import backfill_reviews, backfill_ledger, backfill_premium
    nr = backfill_reviews()
    nl = backfill_ledger()
    np = backfill_premium()
    return {"target_date": iso, "ok": True,
            "reviews_synced": nr, "ledger_synced": nl, "premium_synced": np}


def run_picks_daily(target_date: str | None = None) -> dict:
    """跑下一交易日选股。

    优先策略：
    1. 查找 `generate_fengmang_breakout_<next_compact>.py`，存在则执行
    2. 否则：标 health_issue "picks_script_missing"，提示需要生成新脚本 / 走 skill
    3. 执行成功后回填 plans 到 DB
    """
    today = today_iso()
    base = latest_trading_day(today)
    next_iso, conf = next_trading_day(base)
    next_compact = next_iso.replace("-", "")

    script_path = CONFIG.legacy_root / f"generate_fengmang_breakout_{next_compact}.py"
    if not script_path.exists():
        with tx() as conn:
            conn.execute(
                "INSERT INTO health_issues (severity, kind, target, detail) VALUES (?,?,?,?)",
                ("warn", "picks_script_missing", next_iso,
                 f"未发现 {script_path}（首次需要按 fengmang-a-share-breakout skill 生成）"),
            )
        return {"target_date": next_iso, "ok": False, "blocked": "script_missing",
                "expected_path": str(script_path), "confidence": conf}

    result = run_python(script_path, kind="picks_daily")
    # 回填 plan
    from core.backfill import backfill_plans
    n = backfill_plans()
    return {"target_date": next_iso, "ok": result["ok"],
            "script": str(script_path), "exit_code": result["exit_code"],
            "duration_ms": result["duration_ms"],
            "plans_synced": n}


def run_backfill_sync(target_date: str | None = None) -> dict:
    from core.backfill import backfill_all
    r = backfill_all()
    return r


def run_health_check(target_date: str | None = None) -> dict:
    """跑数据健康检查。"""
    from core.health import run_all_checks
    return run_all_checks()


RUNNERS = {
    "run_ladder_refresh": run_ladder_refresh,
    "run_review_daily": run_review_daily,
    "run_picks_daily": run_picks_daily,
    "run_backfill_sync": run_backfill_sync,
    "run_health_check": run_health_check,
}


# --- 执行入口 ---------------------------------------------------------------

def run_job(name: str, target_date: str | None = None,
            forced: bool = False) -> dict:
    spec = next((j for j in JOBS if j.name == name), None)
    if not spec:
        return {"ok": False, "error": f"unknown job {name}"}

    if not acquire_lock(name):
        return {"ok": False, "error": "locked", "note": "另一次同名任务正在跑"}

    started_perf = time.time()
    # 加毫秒后缀确保 UNIQUE
    started_at = fmt_now() + "." + str(int((started_perf - int(started_perf)) * 1000)).zfill(3)
    target = target_date or today_iso()
    artifacts: dict = {}
    status = "ok"
    message = ""
    runner = RUNNERS[spec.runner]
    try:
        result = runner(target_date=target_date)
        artifacts = result or {}
        if isinstance(result, dict):
            if result.get("ok") is False:
                status = "failed" if not result.get("skipped") else "skipped"
                message = result.get("error") or result.get("blocked") or result.get("reason") or ""
            elif result.get("skipped"):
                status = "skipped"
                message = result.get("reason", "")
    except Exception as e:
        status = "failed"
        message = f"{type(e).__name__}: {e}"
        artifacts = {"error": message}
    finally:
        release_lock(name)

    finished_at = fmt_now()
    duration_ms = int((time.time() - started_perf) * 1000)

    with tx() as conn:
        conn.execute(
            """INSERT INTO job_runs
            (job_name, started_at, finished_at, target_date, status, message, artifacts_json)
            VALUES (?,?,?,?,?,?,?)""",
            (name, started_at, finished_at, target, status, message,
             json.dumps(artifacts, ensure_ascii=False, default=str)),
        )
        # upsert jobs
        conn.execute(
            """INSERT INTO jobs (name, cron_hint, enabled, last_run_at, last_status,
                                  last_message, last_target_date, consecutive_failures)
               VALUES (?,?,1,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 cron_hint=excluded.cron_hint,
                 last_run_at=excluded.last_run_at,
                 last_status=excluded.last_status,
                 last_message=excluded.last_message,
                 last_target_date=excluded.last_target_date,
                 consecutive_failures=CASE WHEN excluded.last_status='failed'
                                           THEN consecutive_failures + 1 ELSE 0 END
            """,
            (name, spec.cron_hint, finished_at, status, message[:500], target,
             1 if status == "failed" else 0),
        )
    return {"name": name, "status": status, "message": message,
            "duration_ms": duration_ms, "artifacts": artifacts}


# --- 后台调度循环 -----------------------------------------------------------

class Scheduler:
    """单线程后台 ticker。"""

    def __init__(self):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # 用 (date_iso, job_name) 跟踪当日是否已成功
        self._last_runs: dict[str, str] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # 上次执行的轻量任务的时间戳
        last_hourly = 0.0
        last_10min = 0.0
        while not self._stop.is_set():
            try:
                self._tick(last_hourly, last_10min)
                # 更新心跳间隔变量
                t = time.time()
                if t - last_hourly >= 3600:
                    last_hourly = t
                if t - last_10min >= 600:
                    last_10min = t
            except Exception:
                pass
            self._stop.wait(timeout=30)

    def _tick(self, last_hourly: float, last_10min: float) -> None:
        n = now()
        weekday = n.isoweekday()  # 1..7
        cur_min = n.hour * 60 + n.minute
        today = today_iso()
        t = time.time()

        for spec in JOBS:
            # 周期型
            if spec.schedule_minute < 0:
                if spec.name == "backfill_sync":
                    if t - last_hourly >= 3600:
                        run_job(spec.name)
                elif spec.name == "health_check":
                    if t - last_10min >= 600:
                        run_job(spec.name)
                continue

            # 定时型
            if spec.weekday_only and weekday > 5:
                continue
            if cur_min < spec.schedule_minute or cur_min > spec.end_minute:
                continue

            # 当日是否已成功
            key = f"{today}:{spec.name}"
            if self._last_runs.get(key) == "ok":
                continue
            # 也从 DB 查最近一次
            conn = get_conn()
            try:
                row = conn.execute(
                    "SELECT status FROM job_runs WHERE job_name=? AND target_date>=? "
                    "ORDER BY id DESC LIMIT 1",
                    (spec.name, today),
                ).fetchone()
            finally:
                conn.close()
            if row and row["status"] in ("ok",):
                self._last_runs[key] = "ok"
                continue

            # 跑
            result = run_job(spec.name)
            if result.get("status") == "ok":
                self._last_runs[key] = "ok"


SCHEDULER = Scheduler()


def start_scheduler() -> None:
    SCHEDULER.start()
