"""统一时区 / 日期工具：Asia/Shanghai。"""
from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo


TZ = ZoneInfo("Asia/Shanghai")


def now() -> _dt.datetime:
    """返回上海时区的"当前时刻"。"""
    return _dt.datetime.now(TZ)


def today_iso() -> str:
    return now().date().isoformat()


def today_compact() -> str:
    return now().date().strftime("%Y%m%d")


def to_compact(iso_date: str) -> str:
    """2026-06-22 -> 20260622。"""
    if not iso_date:
        return ""
    return iso_date.replace("-", "")[:8]


def to_iso(compact: str) -> str:
    """20260622 -> 2026-06-22。"""
    if not compact:
        return ""
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"


def fmt_dt(dt: _dt.datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def fmt_now() -> str:
    return now().strftime("%Y-%m-%d %H:%M:%S")
