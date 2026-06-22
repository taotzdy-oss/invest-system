"""复盘适配器：读取 `锋芒爆点_复盘迭代/*`。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from adapters.files import read_csv_rows, read_text
from core.config import CONFIG


PREMIUM_FIELDS = [
    "晋级日期", "溢价观察日", "代码", "名称", "晋级日收盘价", "次日开盘价",
    "10点前最高价", "10点前最低价", "10点价",
    "开盘溢价%", "10点前最高溢价%", "10点价溢价%", "10点前最低溢价%",
    "形态", "结论", "数据来源",
]


LEDGER_FIELDS = [
    "交易日期", "策略组", "代码", "名称", "计划级别", "计划角色", "计划评分",
    "计划触发条件", "计划放弃条件", "实际结果", "是否触板", "是否封住",
    "首次触板时间", "最后封板时间", "炸板次数", "成交额", "换手率",
    "主题反馈", "差异类型", "经验标签", "证据来源", "复盘报告路径",
]


@dataclass
class ReviewDay:
    date: str           # 20260612
    iso_date: str       # 2026-06-12
    dir_path: Path
    report_path: Path | None


def _iso(d8: str) -> str:
    return f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}" if len(d8) == 8 else d8


def list_review_days() -> list[ReviewDay]:
    root = CONFIG.legacy_path("review_daily_dir")
    if not root.exists():
        return []
    days: list[ReviewDay] = []
    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        if not re.fullmatch(r"\d{8}", sub.name):
            continue
        report = None
        for f in sub.iterdir():
            if f.is_file() and f.name.endswith("_复盘报告.md"):
                report = f
                break
        days.append(ReviewDay(date=sub.name, iso_date=_iso(sub.name),
                              dir_path=sub, report_path=report))
    days.sort(key=lambda x: x.date, reverse=True)
    return days


def get_review_day(date: str) -> ReviewDay | None:
    d8 = date.replace("-", "")
    for d in list_review_days():
        if d.date == d8:
            return d
    return None


def ledger_rows() -> list[dict]:
    return read_csv_rows(CONFIG.legacy_path("review_ledger_csv"))


def bucket_rows(name: str) -> list[dict]:
    """name 取：成功晋级池 / 失败晋级池 / 失败样本池 / 失败上板池。"""
    buckets_dir = CONFIG.legacy_path("review_buckets_dir")
    fp = buckets_dir / f"{name}.csv"
    return read_csv_rows(fp)


def bucket_summary() -> dict[str, int]:
    out = {}
    for name in ("成功晋级池", "失败晋级池", "失败样本池", "失败上板池"):
        out[name] = len(bucket_rows(name))
    return out


def experience_md() -> str:
    return read_text(CONFIG.legacy_path("review_experience_md"))


def strategy_iteration_md() -> str:
    return read_text(CONFIG.legacy_path("strategy_iteration_md"))


def review_template_md() -> str:
    return read_text(CONFIG.legacy_path("review_template_md"))


def premium_rows() -> list[dict]:
    p = CONFIG.legacy_path("review_ledger_csv").parent / "次日溢价跟踪.csv"
    return read_csv_rows(p)


def parse_review_report(md: str) -> dict:
    """从复盘报告 Markdown 中抽取结构化字段。"""
    out: dict = {
        "basic": {},
        "market": {},
        "metrics": {},
        "premium_review": [],
        "buckets": {},
        "experience": "",
        "action": "",
        "sources": [],
    }
    sections: dict[str, list[str]] = {}
    current = "__head__"
    for line in md.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            current = m.group(1).strip()
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)

    def _section(name: str) -> list[str]:
        return sections.get(name, [])

    def _kv_lines(lines: list[str]) -> dict:
        d = {}
        for line in lines:
            mm = re.match(r"^-\s+([^:：]+)[:：]\s*(.*)$", line.strip())
            if mm:
                d[mm.group(1).strip()] = mm.group(2).strip()
        return d

    out["basic"] = _kv_lines(_section("基本信息"))
    out["market"] = _kv_lines(_section("市场实际情况"))
    out["metrics_lines"] = [l.strip() for l in _section("指标统计") if l.strip()]
    out["buckets_lines"] = [l.strip() for l in _section("晋级分层") if l.strip()]
    out["premium_review_lines"] = [l.strip() for l in _section("次日溢价回看") if l.strip()]
    out["experience"] = "\n".join(_section("策略差异与经验")).strip()
    out["action"] = "\n".join(_section("策略动作")).strip()

    # 数据来源 URL
    for line in _section("基本信息") + sections.get("__head__", []):
        urls = re.findall(r"https?://\S+", line)
        out["sources"].extend(urls)

    return out


def latest_review_day() -> "ReviewDay | None":
    days = list_review_days()
    return days[0] if days else None


def ledger_index() -> dict:
    """生成台账聚合统计：总样本/封板率/按策略组分布/按日期分布。"""
    rows = ledger_rows()
    total = len(rows)
    sealed = sum(1 for r in rows if r.get("是否封住") == "是")
    touched = sum(1 for r in rows if r.get("是否触板") == "是")
    by_date: dict[str, int] = {}
    by_strategy: dict[str, int] = {}
    by_level: dict[str, int] = {}
    for r in rows:
        by_date[r.get("交易日期", "")] = by_date.get(r.get("交易日期", ""), 0) + 1
        by_strategy[r.get("策略组", "")] = by_strategy.get(r.get("策略组", ""), 0) + 1
        by_level[r.get("计划级别", "")] = by_level.get(r.get("计划级别", ""), 0) + 1
    return {
        "total": total,
        "sealed": sealed,
        "touched": touched,
        "seal_rate": (sealed / total * 100) if total else 0,
        "touch_rate": (touched / total * 100) if total else 0,
        "by_date": sorted(by_date.items()),
        "by_strategy": sorted(by_strategy.items()),
        "by_level": sorted(by_level.items()),
    }
