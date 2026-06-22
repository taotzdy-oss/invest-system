"""一次性 / 幂等回填脚本：把旧项目所有历史数据导入 system.db。

设计原则：
- 完全幂等：用 INSERT OR REPLACE / UPSERT，可重复运行
- 所有写都在事务里
- 出错记录到 health_issues，继续下一项，不中断
- 全程不修改旧项目任何文件
"""
from __future__ import annotations

import json
from pathlib import Path

from adapters import knowledge_base as kb_adapter
from adapters import review as rv_adapter
from adapters import stock_pick as sp_adapter
from adapters import strategy as st_adapter
from adapters.files import read_csv_rows, read_text
from core.calendar import confirmed_trading_days
from core.clock import to_compact, fmt_now
from core.config import CONFIG
from core.db import tx


def _flag_issue(conn, severity, kind, target, detail):
    conn.execute(
        "INSERT INTO health_issues (severity, kind, target, detail) VALUES (?,?,?,?)",
        (severity, kind, target, detail),
    )


def backfill_trading_days() -> int:
    n = 0
    with tx() as conn:
        for iso in sorted(confirmed_trading_days()):
            compact = to_compact(iso)
            # weekday
            import datetime as dt
            wd = dt.date.fromisoformat(iso).isoweekday()
            conn.execute(
                "INSERT OR REPLACE INTO trading_days (iso_date, compact, weekday, source) VALUES (?,?,?,?)",
                (iso, compact, wd, "ladder+plan+review"),
            )
            n += 1
    return n


def backfill_plans() -> int:
    n = 0
    pools = sp_adapter.list_pools()
    with tx() as conn:
        for pool in pools:
            try:
                codes = sp_adapter.parse_csv_codes(pool)
                candidates = sp_adapter.parse_html_candidates(pool)
                # 取市场结论摘要（仅供 dashboard 展示）
                market_summary = ""
                theme_summary = ""
                risk_summary = ""
                execution_summary = ""
                if pool.html_path and pool.html_path.exists():
                    import re
                    html = read_text(pool.html_path)
                    paras = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL)
                    cleaned = []
                    for p in paras[:8]:
                        t = re.sub(r"<[^>]+>", "", p).strip()
                        if t:
                            cleaned.append(t)
                    market_summary = cleaned[1] if len(cleaned) > 1 else ""
                    theme_summary = cleaned[2] if len(cleaned) > 2 else ""
                    risk_summary = cleaned[3] if len(cleaned) > 3 else ""
                    execution_summary = cleaned[4] if len(cleaned) > 4 else ""

                # source script: 匹配 NEXT_DATE
                source_script = ""
                for s in st_adapter.list_strategy_scripts():
                    if s.next_date == pool.iso_date or s.params.get("NEXT_COMPACT") == pool.date:
                        source_script = str(s.path)
                        break

                snapshot = {
                    "candidates": candidates,
                    "references": sp_adapter.parse_html_references(pool),
                    "csv_codes": codes,
                }

                conn.execute(
                    """INSERT OR REPLACE INTO plans
                    (trade_date, compact, pool_dir, html_path, csv_path,
                     csv_codes_json, candidates_json, market_summary, theme_summary,
                     risk_summary, execution_summary, source_script, snapshot_json,
                     created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,
                            COALESCE((SELECT created_at FROM plans WHERE trade_date=?), datetime('now','localtime')),
                            datetime('now','localtime'))""",
                    (pool.iso_date, pool.date, str(pool.dir_path),
                     str(pool.html_path) if pool.html_path else "",
                     str(pool.csv_path) if pool.csv_path else "",
                     json.dumps(codes, ensure_ascii=False),
                     json.dumps(candidates, ensure_ascii=False),
                     market_summary, theme_summary, risk_summary, execution_summary,
                     source_script,
                     json.dumps(snapshot, ensure_ascii=False),
                     pool.iso_date),
                )

                # 候选展开
                conn.execute("DELETE FROM plan_candidates WHERE trade_date=?", (pool.iso_date,))
                for idx, c in enumerate(candidates):
                    score = c.get("评分", "")
                    try:
                        score_i = int(score) if score else None
                    except ValueError:
                        score_i = None
                    conn.execute(
                        """INSERT OR REPLACE INTO plan_candidates
                        (trade_date, code, name, role, rank, score, role_label,
                         theme, industry, stage, pressure, next_day_board_price,
                         trigger, abandon, risk_tag, raw_json)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (pool.iso_date, c.get("代码", ""), c.get("名称", ""),
                         c.get("分组", ""), idx + 1, score_i, c.get("角色", ""),
                         c.get("题材", ""), c.get("行业", ""), c.get("梯队", ""),
                         c.get("前压/日期", ""), c.get("次日板价/结构", ""),
                         c.get("临盘触发条件", ""), c.get("放弃条件", ""), "",
                         json.dumps(c, ensure_ascii=False)),
                    )
                n += 1
            except Exception as e:
                _flag_issue(conn, "warn", "backfill_plan", pool.iso_date, str(e))
    return n


def backfill_reviews() -> int:
    n = 0
    days = rv_adapter.list_review_days()
    with tx() as conn:
        for d in days:
            try:
                md = ""
                parsed = {}
                if d.report_path and d.report_path.exists():
                    md = d.report_path.read_text(encoding="utf-8")
                    parsed = rv_adapter.parse_review_report(md)

                snap = {"parsed": parsed, "report_md_len": len(md)}
                sources = parsed.get("sources", []) if isinstance(parsed, dict) else []
                conn.execute(
                    """INSERT OR REPLACE INTO reviews
                    (trade_date, compact, report_path,
                     market_state, breadth, top_themes, risk_feedback,
                     metrics_json, snapshot_json, sources_json,
                     created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,
                            COALESCE((SELECT created_at FROM reviews WHERE trade_date=?), datetime('now','localtime')),
                            datetime('now','localtime'))""",
                    (d.iso_date, d.date, str(d.report_path) if d.report_path else "",
                     parsed.get("market", {}).get("指数与成交", "") if isinstance(parsed.get("market"), dict) else "",
                     parsed.get("market", {}).get("广度与情绪", "") if isinstance(parsed.get("market"), dict) else "",
                     parsed.get("market", {}).get("领涨方向", "") if isinstance(parsed.get("market"), dict) else "",
                     parsed.get("market", {}).get("候选主题反馈", "") if isinstance(parsed.get("market"), dict) else "",
                     json.dumps(parsed, ensure_ascii=False),
                     json.dumps(snap, ensure_ascii=False),
                     json.dumps(sources, ensure_ascii=False),
                     d.iso_date),
                )
                n += 1
            except Exception as e:
                _flag_issue(conn, "warn", "backfill_review", d.iso_date, str(e))
    return n


def backfill_ledger() -> int:
    """从复盘样本台账 CSV 导入逐股结果。"""
    rows = rv_adapter.ledger_rows()
    n = 0
    with tx() as conn:
        # 全量清空再插入：因为是只读 CSV，唯一权威源
        conn.execute("DELETE FROM review_results WHERE strategy_group='正式' OR strategy_group IS NULL OR strategy_group=''")
        for r in rows:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO review_results
                    (trade_date, strategy_group, code, name, plan_level, plan_role,
                     plan_score, plan_trigger, plan_abandon, actual_result,
                     touched, sealed, first_touch_time, last_seal_time,
                     break_count, turnover_amount, turnover_rate, theme_feedback,
                     diff_kind, experience_tag, evidence_source, report_path, raw_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("交易日期", ""), r.get("策略组", "正式") or "正式",
                     r.get("代码", ""), r.get("名称", ""),
                     r.get("计划级别", ""), r.get("计划角色", ""),
                     int(r.get("计划评分") or 0) if (r.get("计划评分") or "").strip().lstrip("-").isdigit() else None,
                     r.get("计划触发条件", ""), r.get("计划放弃条件", ""),
                     r.get("实际结果", ""), r.get("是否触板", ""), r.get("是否封住", ""),
                     r.get("首次触板时间", ""), r.get("最后封板时间", ""),
                     r.get("炸板次数", ""), r.get("成交额", ""), r.get("换手率", ""),
                     r.get("主题反馈", ""), r.get("差异类型", ""),
                     r.get("经验标签", ""), r.get("证据来源", ""),
                     r.get("复盘报告路径", ""),
                     json.dumps(r, ensure_ascii=False)),
                )
                n += 1
            except Exception as e:
                _flag_issue(conn, "warn", "backfill_ledger", r.get("交易日期", "?"), str(e))
    return n


def backfill_premium() -> int:
    rows = rv_adapter.premium_rows()
    n = 0
    with tx() as conn:
        for r in rows:
            try:
                def f(name):
                    v = (r.get(name) or "").strip()
                    try:
                        return float(v) if v else None
                    except ValueError:
                        return None
                conn.execute(
                    """INSERT OR REPLACE INTO premium_tracking
                    (promotion_date, premium_date, code, name,
                     prev_close, next_open, high_before_10, low_before_10, price_10,
                     open_premium_pct, high_premium_pct, p10_premium_pct, low_premium_pct,
                     shape, conclusion, data_source, raw_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("晋级日期", ""), r.get("溢价观察日", ""),
                     r.get("代码", ""), r.get("名称", ""),
                     f("晋级日收盘价"), f("次日开盘价"),
                     f("10点前最高价"), f("10点前最低价"), f("10点价"),
                     f("开盘溢价%"), f("10点前最高溢价%"),
                     f("10点价溢价%"), f("10点前最低溢价%"),
                     r.get("形态", ""), r.get("结论", ""), r.get("数据来源", ""),
                     json.dumps(r, ensure_ascii=False)),
                )
                n += 1
            except Exception as e:
                _flag_issue(conn, "warn", "backfill_premium", r.get("代码", "?"), str(e))
    return n


def backfill_ladder() -> int:
    """连板天梯日概览 + 次日打板建议。"""
    n = 0
    with tx() as conn:
        daily_csv = CONFIG.legacy_path("ladder_data_dir") / "连板天梯_日期概览.csv"
        advice_csv = CONFIG.legacy_path("ladder_data_dir") / "连板天梯_次日打板建议.csv"

        for r in read_csv_rows(daily_csv):
            iso = r.get("日期", "")
            if not iso:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO ladder_daily (iso_date, raw_json) VALUES (?,?)",
                (iso, json.dumps(r, ensure_ascii=False)),
            )
            n += 1

        for r in read_csv_rows(advice_csv):
            iso = r.get("日期", "")
            if not iso:
                continue
            conn.execute(
                """INSERT OR REPLACE INTO ladder_advice
                (iso_date, 强度, 可打板, 可打级别, 建议仓位, 判断依据, raw_json)
                VALUES (?,?,?,?,?,?,?)""",
                (iso, r.get("连板强度", ""), r.get("次日是否可打板", ""),
                 r.get("可打晋级板", ""), r.get("建议仓位", ""),
                 r.get("判断依据", ""), json.dumps(r, ensure_ascii=False)),
            )
    return n


def backfill_all() -> dict:
    out = {"started_at": fmt_now()}
    out["trading_days"] = backfill_trading_days()
    out["plans"] = backfill_plans()
    out["reviews"] = backfill_reviews()
    out["ledger"] = backfill_ledger()
    out["premium"] = backfill_premium()
    out["ladder"] = backfill_ladder()
    out["finished_at"] = fmt_now()
    return out


if __name__ == "__main__":
    result = backfill_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))
