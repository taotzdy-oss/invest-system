"""A 股交易日工具。

权威来源：旧项目 `A股连板天梯/data/连板天梯_日期概览.csv` —— 该 CSV 中出现过的"日期"
就是真实成交日（数据由旧脚本基于真实开盘红涨停天梯回补）。

本模块的策略：
1. 主源：ladder 日期概览 + 历次复盘 + 历次观察池产生的所有日期，全部视为"已确认交易日"。
2. 兜底：若被问到一个未来日期，按周末 + 大致中国节假日表（手工维护小集合）排除，给"猜测"答案，
   并标 `confidence='guessed'`。永远不在 dashboard / 自动任务里用未经 ladder 确认的交易日产生 plan。
3. 所有时间用 Asia/Shanghai。
"""
from __future__ import annotations

import csv
import datetime as _dt
import re
from functools import lru_cache
from pathlib import Path

from core.clock import TZ, to_compact, to_iso
from core.config import CONFIG


# 已知节假日（手工维护，仅作"猜测下一交易日"使用；正式判断仍以 ladder 出现过的日期为准）。
KNOWN_HOLIDAYS_2026 = {
    "2026-01-01",
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    "2026-04-03", "2026-04-06",
    "2026-05-01", "2026-05-04", "2026-05-05",
    "2026-06-19",  # 端午（0622 是端午节后首个交易日）
    "2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30",
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
}


def _ladder_dates_iter():
    p = Path(CONFIG.legacy_root) / "A股连板天梯/data/连板天梯_日期概览.csv"
    if not p.exists():
        return
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            d = (row.get("日期") or "").strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
                yield d


@lru_cache(maxsize=1)
def confirmed_trading_days() -> set[str]:
    days: set[str] = set()
    # 来源 1：ladder
    days.update(_ladder_dates_iter())
    # 来源 2：观察池目录
    root = Path(CONFIG.legacy_root)
    for p in root.glob("锋芒爆点_*_打板观察池"):
        m = re.search(r"_(\d{8})_", p.name)
        if m:
            days.add(to_iso(m.group(1)))
    # 来源 3：复盘日期
    review_dir = Path(CONFIG.legacy_root) / "锋芒爆点_复盘迭代/每日复盘"
    if review_dir.exists():
        for sub in review_dir.iterdir():
            if sub.is_dir() and re.fullmatch(r"\d{8}", sub.name):
                days.add(to_iso(sub.name))
    return days


def is_confirmed_trading_day(iso_date: str) -> bool:
    return iso_date in confirmed_trading_days()


def is_likely_trading_day(iso_date: str) -> bool:
    """对未来日期做"猜测"：非周末 + 不在已知节假日集合。"""
    try:
        d = _dt.date.fromisoformat(iso_date)
    except ValueError:
        return False
    if d.weekday() >= 5:
        return False
    if iso_date in KNOWN_HOLIDAYS_2026:
        return False
    return True


def latest_trading_day(today_iso: str) -> str:
    """返回 <= today 的最近确认交易日。如果今日就是确认交易日，返回今日。"""
    days = confirmed_trading_days()
    # 直接命中
    if today_iso in days:
        return today_iso
    # 否则在确认集合里找最大的 <= today
    candidates = sorted([d for d in days if d <= today_iso], reverse=True)
    return candidates[0] if candidates else today_iso


def next_trading_day(after_iso: str) -> tuple[str, str]:
    """返回 (next_iso, confidence)。优先用确认集合里 > after 的最小日期；
    没有就猜测。"""
    days = sorted(confirmed_trading_days())
    later = [d for d in days if d > after_iso]
    if later:
        return later[0], "confirmed"
    # 猜测
    d = _dt.date.fromisoformat(after_iso) + _dt.timedelta(days=1)
    for _ in range(14):
        if is_likely_trading_day(d.isoformat()):
            return d.isoformat(), "guessed"
        d += _dt.timedelta(days=1)
    return d.isoformat(), "guessed"


def recent_trading_days(n: int, before_iso: str | None = None) -> list[str]:
    """返回最近 n 个已确认交易日，按时间倒序。"""
    days = sorted(confirmed_trading_days(), reverse=True)
    if before_iso:
        days = [d for d in days if d <= before_iso]
    return days[:n]
