"""统一首页（dashboard）数据聚合层。

把所有 6 大区块需要的数据，整理为一个 dict 返回给 modules/dashboard.py 渲染。
任何地方都以 DB 为唯一数据来源（旧项目原文件作为可追溯证据）。
"""
from __future__ import annotations

import json
from collections import Counter

from core.calendar import (
    confirmed_trading_days, latest_trading_day, next_trading_day,
    recent_trading_days,
)
from core.clock import now, today_iso
from core.config import CONFIG
from core.db import get_conn


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def _pct(x, total) -> float:
    return (x / total * 100) if total else 0


def _safe_json(s: str | None):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def section_today_overview() -> dict:
    """今日总览：交易日 / 指数 / 广度 / 涨停高度 / 主线 / 风险 / 自动任务状态。"""
    conn = get_conn()
    try:
        today = today_iso()
        latest = latest_trading_day(today)
        next_iso, conf = next_trading_day(latest)
        # ladder 概览 / advice（最新一日）
        d_row = conn.execute(
            "SELECT * FROM ladder_daily WHERE iso_date<=? ORDER BY iso_date DESC LIMIT 1", (latest,)
        ).fetchone()
        ladder = _safe_json(d_row["raw_json"]) if d_row else None

        a_row = conn.execute(
            "SELECT * FROM ladder_advice WHERE iso_date<=? ORDER BY iso_date DESC LIMIT 1", (latest,)
        ).fetchone()
        advice = _row_to_dict(a_row)

        # 当日复盘（如果有）
        rv_row = conn.execute(
            "SELECT * FROM reviews WHERE trade_date=?", (latest,)
        ).fetchone()
        review = _row_to_dict(rv_row)

        # 自动任务最近状态
        jobs = [dict(r) for r in conn.execute(
            "SELECT name, cron_hint, last_run_at, last_status, last_message, last_target_date "
            "FROM jobs ORDER BY name"
        ).fetchall()]

        # 风险开关：近 3 日触板率 / 失败晋级 / 高炸板封住 等综合
        recent_metrics = section_recent_metrics(5)

        return {
            "today_iso": today,
            "latest_trading_day": latest,
            "next_trading_day": next_iso,
            "next_trading_day_confidence": conf,
            "ladder": ladder,
            "advice": advice,
            "review": review,
            "jobs": jobs,
            "recent_metrics": recent_metrics,
            "now_ts": now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    finally:
        conn.close()


def section_tomorrow_plan() -> dict:
    """明日计划：最新一份 plan + 候选展开 + 20%/30% 参考。"""
    conn = get_conn()
    try:
        plan = conn.execute(
            "SELECT * FROM plans ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if not plan:
            return {"empty": True}
        td = plan["trade_date"]
        cands = [dict(r) for r in conn.execute(
            "SELECT * FROM plan_candidates WHERE trade_date=? ORDER BY rank", (td,)
        ).fetchall()]
        snapshot = _safe_json(plan["snapshot_json"]) or {}
        return {
            "trade_date": td,
            "pool_dir": plan["pool_dir"],
            "html_path": plan["html_path"],
            "csv_path": plan["csv_path"],
            "csv_codes": _safe_json(plan["csv_codes_json"]) or [],
            "market_summary": plan["market_summary"],
            "theme_summary": plan["theme_summary"],
            "risk_summary": plan["risk_summary"],
            "execution_summary": plan["execution_summary"],
            "candidates": cands,
            "references": snapshot.get("references", []),
            "th_status": plan["th_import_status"],
            "th_note": plan["th_import_note"],
        }
    finally:
        conn.close()


def section_today_review() -> dict:
    """当日复盘。"""
    conn = get_conn()
    try:
        latest_review = conn.execute(
            "SELECT * FROM reviews ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if not latest_review:
            return {"empty": True}
        td = latest_review["trade_date"]
        # 该日逐股结果
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM review_results WHERE trade_date=? ORDER BY plan_level, code", (td,)
        ).fetchall()]
        # 同一日的"明日计划"行（追溯）
        plan_candidates = [dict(r) for r in conn.execute(
            "SELECT * FROM plan_candidates WHERE trade_date=? ORDER BY rank", (td,)
        ).fetchall()]
        # 各分桶
        success = [r for r in rows if r["sealed"] == "是"]
        failed_promotion = [r for r in rows if r["touched"] == "是" and r["sealed"] != "是"]
        failed_sample = [r for r in rows if r["touched"] != "是"]
        one_word = [r for r in rows if (r["actual_result"] or "").startswith("一字")]
        afternoon_seal = [r for r in rows if r["sealed"] == "是" and (r["last_seal_time"] or "")[:2] in ("13", "14", "15")]
        high_break_seal = [r for r in rows if r["sealed"] == "是" and (r["break_count"] or "").isdigit() and int(r["break_count"]) >= 5]
        metrics = _compute_metrics(rows)

        parsed = _safe_json(latest_review["metrics_json"]) or {}
        # 上一交易日 premium
        all_days = sorted(confirmed_trading_days())
        prev_premium = []
        if td in all_days:
            idx = all_days.index(td)
            if idx > 0:
                prev_date = all_days[idx - 1]
                prev_premium = [dict(r) for r in conn.execute(
                    "SELECT * FROM premium_tracking WHERE promotion_date=? ORDER BY code", (prev_date,)
                ).fetchall()]

        return {
            "trade_date": td,
            "compact": latest_review["compact"],
            "report_path": latest_review["report_path"],
            "market_state": latest_review["market_state"],
            "breadth": latest_review["breadth"],
            "top_themes": latest_review["top_themes"],
            "risk_feedback": latest_review["risk_feedback"],
            "rows": rows,
            "plan_candidates": plan_candidates,
            "success": success,
            "failed_promotion": failed_promotion,
            "failed_sample": failed_sample,
            "one_word": one_word,
            "afternoon_seal": afternoon_seal,
            "high_break_seal": high_break_seal,
            "metrics": metrics,
            "parsed_review": parsed,
            "prev_premium": prev_premium,
        }
    finally:
        conn.close()


def _compute_metrics(rows: list[dict]) -> dict:
    n = len(rows)
    touched = sum(1 for r in rows if r["touched"] == "是")
    sealed = sum(1 for r in rows if r["sealed"] == "是")
    burst = touched - sealed
    actionable = sum(
        1 for r in rows
        if r["sealed"] == "是" and not (r["actual_result"] or "").startswith("一字")
    )
    return {
        "total": n,
        "touched": touched,
        "sealed": sealed,
        "burst": burst,
        "actionable": actionable,
        "touch_rate": round(_pct(touched, n), 1),
        "seal_rate": round(_pct(sealed, n), 1),
        "burst_rate": round(_pct(burst, touched), 1) if touched else 0,
        "actionable_rate": round(_pct(actionable, n), 1),
    }


def section_recent_metrics(window: int = 5) -> dict:
    """最近 N 个交易日聚合指标。"""
    conn = get_conn()
    try:
        days = recent_trading_days(window)
        out = {"window": window, "days": days, "daily": []}
        all_rows: list[dict] = []
        for d in days:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM review_results WHERE trade_date=?", (d,)
            ).fetchall()]
            metrics = _compute_metrics(rows)
            metrics["date"] = d
            metrics["sample"] = len(rows)
            out["daily"].append(metrics)
            all_rows.extend(rows)
        out["aggregate"] = _compute_metrics(all_rows)

        # 按角色
        out["by_level"] = {}
        for lv in ("主选", "条件", "备选"):
            sub = [r for r in all_rows if r.get("plan_level") == lv]
            out["by_level"][lv] = _compute_metrics(sub)

        return out
    finally:
        conn.close()


def section_trend_analysis() -> dict:
    """趋势分析：最近 5/10/20 日表现 + 1进2/2进3/3进4 等。"""
    conn = get_conn()
    try:
        out = {}
        for w in (5, 10, 20):
            out[f"last_{w}"] = section_recent_metrics(w)

        # 次日溢价表现
        premium = [dict(r) for r in conn.execute(
            "SELECT * FROM premium_tracking ORDER BY promotion_date DESC, code LIMIT 100"
        ).fetchall()]
        out["premium"] = premium
        # 可兑现率
        valid = [p for p in premium if p["high_premium_pct"] is not None]
        with_premium = [p for p in valid if (p["high_premium_pct"] or 0) > 0]
        out["premium_actionable_rate"] = round(_pct(len(with_premium), len(valid)), 1) if valid else 0

        # 形态分布
        out["shape_dist"] = dict(Counter(p["shape"] for p in premium if p["shape"]))

        return out
    finally:
        conn.close()


def section_strategy_iteration() -> dict:
    """策略迭代：当前正式策略 + 经验库摘要 + 样本数。"""
    from adapters import review as rv
    conn = get_conn()
    try:
        sample_count = conn.execute("SELECT COUNT(*) c FROM review_results").fetchone()["c"]
        review_day_count = conn.execute("SELECT COUNT(*) c FROM reviews").fetchone()["c"]

        thresholds = {
            "observation": (1, 1),
            "reusable":    (5, 20),
            "control":     (10, 50),
        }
        progress = {}
        for k, (days_th, cands_th) in thresholds.items():
            progress[k] = {
                "days_threshold": days_th,
                "cands_threshold": cands_th,
                "days_current": review_day_count,
                "cands_current": sample_count,
                "days_remaining": max(0, days_th - review_day_count),
                "cands_remaining": max(0, cands_th - sample_count),
                "met": review_day_count >= days_th and sample_count >= cands_th,
            }

        return {
            "sample_count": sample_count,
            "review_day_count": review_day_count,
            "progress": progress,
            "experience_md": rv.experience_md(),
            "iteration_md": rv.strategy_iteration_md(),
            "official_strategy_skill": "/Users/gegezi/.codex/skills/fengmang-a-share-breakout/SKILL.md",
            "review_skill": "/Users/gegezi/.codex/skills/fengmang-a-share-breakout-review/SKILL.md",
        }
    finally:
        conn.close()


def section_system_health() -> dict:
    """系统健康。"""
    conn = get_conn()
    try:
        jobs = [dict(r) for r in conn.execute(
            "SELECT name, cron_hint, last_run_at, last_status, last_message, "
            "last_target_date, consecutive_failures FROM jobs ORDER BY name"
        ).fetchall()]
        runs = [dict(r) for r in conn.execute(
            "SELECT * FROM job_runs ORDER BY id DESC LIMIT 30"
        ).fetchall()]
        issues = [dict(r) for r in conn.execute(
            "SELECT * FROM health_issues WHERE resolved_at IS NULL "
            "ORDER BY (CASE severity WHEN 'error' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END), id DESC"
        ).fetchall()]
        return {"jobs": jobs, "runs": runs, "issues": issues,
                "now_ts": now().strftime("%Y-%m-%d %H:%M:%S")}
    finally:
        conn.close()


def aggregate() -> dict:
    """一次性聚合所有 6 段数据。"""
    return {
        "today": section_today_overview(),
        "tomorrow": section_tomorrow_plan(),
        "review": section_today_review(),
        "trend": section_trend_analysis(),
        "iteration": section_strategy_iteration(),
        "health": section_system_health(),
    }
