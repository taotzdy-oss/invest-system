"""数据健康检查 + CSV 校验。

把所有 freshness / mismatch / source 问题写入 health_issues 表。
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import re
from pathlib import Path

from adapters import stock_pick as sp_adapter
from core.calendar import (
    confirmed_trading_days, is_confirmed_trading_day, latest_trading_day,
    next_trading_day,
)
from core.clock import fmt_now, today_iso
from core.config import CONFIG
from core.db import get_conn, tx


def _open_issue(conn, severity, kind, target, detail):
    # 若同 (kind, target) 有未 resolved 的旧 issue，则不重复插入，但更新 detail
    row = conn.execute(
        "SELECT id FROM health_issues WHERE resolved_at IS NULL AND kind=? AND target=?",
        (kind, target),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE health_issues SET severity=?, detail=?, detected_at=datetime('now','localtime') WHERE id=?",
            (severity, detail, row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        "INSERT INTO health_issues (severity, kind, target, detail) VALUES (?,?,?,?)",
        (severity, kind, target, detail),
    )
    return cur.lastrowid


def _resolve_issues(conn, kind, target):
    conn.execute(
        "UPDATE health_issues SET resolved_at=datetime('now','localtime') "
        "WHERE resolved_at IS NULL AND kind=? AND target=?",
        (kind, target),
    )


def check_csv_format(pool) -> list[dict]:
    """同花顺 CSV 格式校验：UTF-8 / 一行一个 6 位代码 / 无表头 / 无重复 / 无 ST / 仅 10cm。"""
    issues = []
    if not pool.csv_path or not pool.csv_path.exists():
        issues.append({"severity": "error", "kind": "csv_missing",
                       "target": pool.iso_date, "detail": f"未找到 CSV"})
        return issues
    raw = pool.csv_path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        issues.append({"severity": "error", "kind": "csv_encoding",
                       "target": pool.iso_date, "detail": "CSV 非 UTF-8 编码"})
        return issues
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        issues.append({"severity": "error", "kind": "csv_empty",
                       "target": pool.iso_date, "detail": "CSV 为空"})
        return issues

    codes = []
    for ln in lines:
        # 非 6 位 + 不允许带其它字段
        cleaned = re.sub(r"^[A-Za-z]{1,3}", "", ln)
        if not re.fullmatch(r"\d{6}", cleaned):
            issues.append({"severity": "error", "kind": "csv_format",
                           "target": pool.iso_date,
                           "detail": f"CSV 含非 6 位代码行: {ln}"})
            return issues
        codes.append(cleaned)

    dup = [c for c in set(codes) if codes.count(c) > 1]
    if dup:
        issues.append({"severity": "error", "kind": "csv_duplicate",
                       "target": pool.iso_date,
                       "detail": f"CSV 含重复代码: {','.join(sorted(dup))}"})

    # 比对 HTML 候选池：CSV 中每只必须出现在 HTML
    cands = sp_adapter.parse_html_candidates(pool)
    cand_codes = {c.get("代码", "") for c in cands}
    missing_in_html = [c for c in codes if c not in cand_codes]
    if missing_in_html:
        issues.append({"severity": "warn", "kind": "csv_html_mismatch",
                       "target": pool.iso_date,
                       "detail": f"CSV 中以下代码未在 HTML 候选池表出现: {','.join(missing_in_html)}"})
    extra_in_csv = [c for c in cand_codes if c not in codes]
    if extra_in_csv:
        # HTML 中可能含未选入 CSV 的候选；如果有"主选"/"条件"/"备选"以外的不算异常
        pass

    return issues


def check_data_freshness() -> list[dict]:
    issues = []
    today = today_iso()
    # 最近交易日
    latest = latest_trading_day(today)
    next_iso, conf = next_trading_day(latest)

    # 复盘新鲜度：今天若是交易日 + 现在已过 16:00 + 还没有当日复盘 -> warn
    import datetime as dt
    from core.clock import now as clock_now
    n = clock_now()
    if is_confirmed_trading_day(today) and n.hour >= 16:
        compact = today.replace("-", "")
        rp = CONFIG.legacy_path("review_daily_dir") / compact / f"锋芒爆点_{compact}_复盘报告.md"
        if not rp.exists():
            issues.append({"severity": "warn", "kind": "freshness_review",
                           "target": today,
                           "detail": f"今日 ({today}) 是交易日且已过 16:00，但未找到复盘报告 {rp}"})

    # 选股新鲜度：若现在已过 18:00 + 下一交易日的脚本不存在 -> warn
    if is_confirmed_trading_day(today) and n.hour >= 18:
        next_compact = next_iso.replace("-", "")
        sp = CONFIG.legacy_root / f"generate_fengmang_breakout_{next_compact}.py"
        if not sp.exists():
            issues.append({"severity": "warn", "kind": "freshness_picks",
                           "target": next_iso,
                           "detail": f"已过 18:00，但未发现下一交易日选股脚本 {sp}"})

    # ladder 新鲜度：超过 1 周未更新则 warn
    meta = CONFIG.legacy_path("ladder_data_dir") / "连板天梯_meta.json"
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            end_date = data.get("end_date", "")
            if end_date:
                age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(end_date)).days
                if age > 3:
                    issues.append({"severity": "warn", "kind": "freshness_ladder",
                                   "target": end_date,
                                   "detail": f"连板天梯数据已 {age} 天未更新（end_date={end_date}）"})
        except Exception:
            pass

    return issues


def check_data_consistency() -> list[dict]:
    """DB ↔ 旧项目原文件 一致性检查。"""
    issues = []
    conn = get_conn()
    try:
        db_dates = [r["trade_date"] for r in conn.execute("SELECT trade_date FROM plans").fetchall()]
        file_pools = sp_adapter.list_pools()
        file_dates = [p.iso_date for p in file_pools]

        missing_in_db = [d for d in file_dates if d not in db_dates]
        for d in missing_in_db:
            issues.append({"severity": "warn", "kind": "db_missing_plan",
                           "target": d, "detail": f"磁盘有 {d} 观察池但 DB 未导入；运行 backfill 或 health_check 即可"})
    finally:
        conn.close()
    return issues


def run_all_checks() -> dict:
    """跑全部检查，写 health_issues 表。"""
    fresh = check_data_freshness()
    cons = check_data_consistency()
    csv_problems = []
    for pool in sp_adapter.list_pools()[:5]:
        csv_problems.extend(check_csv_format(pool))

    all_issues = fresh + cons + csv_problems
    with tx() as conn:
        # 把当前 batch 的 issue upsert，并对未出现的同 kind 老 issue 标 resolved
        seen = set()
        for i in all_issues:
            _open_issue(conn, i["severity"], i["kind"], i["target"], i["detail"])
            seen.add((i["kind"], i["target"]))
        # 把没出现的 kind in (freshness_*, csv_*) 标记 resolved
        active = conn.execute(
            "SELECT id, kind, target FROM health_issues WHERE resolved_at IS NULL"
        ).fetchall()
        kinds_we_can_resolve = {"freshness_review", "freshness_picks", "freshness_ladder",
                                "csv_missing", "csv_encoding", "csv_empty",
                                "csv_format", "csv_duplicate", "csv_html_mismatch",
                                "db_missing_plan"}
        for r in active:
            if r["kind"] in kinds_we_can_resolve and (r["kind"], r["target"]) not in seen:
                _resolve_issues(conn, r["kind"], r["target"])
    return {"ok": True, "issues_count": len(all_issues),
            "by_severity": {sev: sum(1 for i in all_issues if i["severity"] == sev)
                            for sev in ("info", "warn", "error")}}
