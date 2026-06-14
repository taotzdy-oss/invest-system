"""每日选股适配器：读取 `锋芒爆点_YYYYMMDD_打板观察池/*` 目录。

数据结构：
- 观察池目录列表（按日期倒序）
- 每个观察池：CSV (代码列表) + HTML 分析结论 + 可能的复核 HTML
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from adapters.files import read_text
from core.config import CONFIG


POOL_RE = re.compile(r"锋芒爆点_(\d{8})_打板观察池$")


@dataclass
class StockPool:
    date: str           # 20260615
    iso_date: str       # 2026-06-15
    dir_path: Path
    csv_path: Path | None
    html_path: Path | None
    extra_htmls: list[Path]


def _iso(d8: str) -> str:
    return f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}" if len(d8) == 8 else d8


def list_pools() -> list[StockPool]:
    root = CONFIG.legacy_root
    pools: list[StockPool] = []
    for p in root.iterdir():
        if not p.is_dir():
            continue
        m = POOL_RE.match(p.name)
        if not m:
            continue
        d8 = m.group(1)
        csv_p = None
        html_p = None
        extras: list[Path] = []
        for f in p.iterdir():
            if not f.is_file():
                continue
            n = f.name.lower()
            if n.endswith(".csv"):
                csv_p = f
            elif n.endswith("_分析结论.html"):
                html_p = f
            elif n.endswith(".html"):
                extras.append(f)
        pools.append(StockPool(
            date=d8, iso_date=_iso(d8), dir_path=p,
            csv_path=csv_p, html_path=html_p, extra_htmls=sorted(extras),
        ))
    pools.sort(key=lambda x: x.date, reverse=True)
    return pools


def get_pool(date: str) -> StockPool | None:
    """date 可传 20260615 或 2026-06-15。"""
    d8 = date.replace("-", "")
    for pool in list_pools():
        if pool.date == d8:
            return pool
    return None


def parse_csv_codes(pool: StockPool) -> list[str]:
    """同花顺导入 CSV 通常每行一个代码（可能含 SH/SZ 前缀）。"""
    if not pool.csv_path or not pool.csv_path.exists():
        return []
    out: list[str] = []
    for line in read_text(pool.csv_path).splitlines():
        s = line.strip().lstrip("﻿")
        if not s:
            continue
        # 去掉可能的市场前缀
        cleaned = re.sub(r"^[A-Za-z]{1,3}", "", s).strip()
        out.append(cleaned)
    return out


def parse_html_candidates(pool: StockPool) -> list[dict]:
    """从 `_分析结论.html` 中抽取候选池表格行。

    HTML 由旧脚本 generate_fengmang_breakout_*.py 生成，
    第一个 <table> 总是"可执行候选池"，列顺序固定。
    """
    if not pool.html_path or not pool.html_path.exists():
        return []
    text = read_text(pool.html_path)
    tables = re.findall(r"<table[^>]*>(.*?)</table>", text, re.DOTALL)
    if not tables:
        return []
    # 候选池表头列
    headers = ["分组", "代码", "名称", "角色", "评分", "执行优先级", "资金结构",
               "梯队", "行业", "题材", "首次封板", "最后封板", "炸板", "成交额",
               "换手", "封单资金", "前压/日期", "次日板价/结构", "临盘触发条件",
               "放弃条件"]
    rows: list[dict] = []
    body = tables[0]
    # 找到 tbody，否则用整体
    m = re.search(r"<tbody[^>]*>(.*?)</tbody>", body, re.DOTALL)
    tbody = m.group(1) if m else body
    for tr_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", tbody, re.DOTALL):
        tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr_match.group(1), re.DOTALL)
        if not tds:
            continue
        cells = [_strip_html(c) for c in tds]
        # 跳过表头行
        if cells and cells[0] in ("分组", "Group"):
            continue
        record = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(headers)}
        if record.get("代码") or record.get("名称"):
            rows.append(record)
    return rows


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def list_scripts() -> list[Path]:
    """列出可选股脚本（generate_fengmang_breakout_*.py）。"""
    return CONFIG.legacy_glob("stock_pick_script_glob")
