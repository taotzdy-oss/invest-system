"""每日选股适配器：读取 `锋芒爆点_YYYYMMDD_打板观察池/*` 目录。

支持新旧两套 HTML 格式：
- 旧（≤2026-06-15）：单表 "可执行候选池"，20 列固定。
- 新（≥2026-06-16）：多个表，按 <h2> 章节区分；候选池表头列动态。

解析方式统一：按表头 <th> 动态读列名，cell 与列名严格对位，避免错列。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from adapters.files import read_text
from core.config import CONFIG


POOL_RE = re.compile(r"锋芒爆点_(\d{8})_打板观察池$")

# 候选池表头识别：含 "代码" + "名称" + ("评分" 或 "分") + ("临盘触发条件" 或 "触发")
CANDIDATE_HEAD_KEYS = ("代码", "名称")
# 不同 HTML 的"分组"/"层级"列别名
GROUP_COL_ALIASES = ("分组", "层级", "级别")
# 评分列别名
SCORE_COL_ALIASES = ("评分", "分")
# 角色描述
ROLE_COL = "角色"


@dataclass
class StockPool:
    date: str           # 20260615
    iso_date: str       # 2026-06-15
    dir_path: Path
    csv_path: Path | None
    html_path: Path | None
    extra_htmls: list[Path] = field(default_factory=list)


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
        cleaned = re.sub(r"^[A-Za-z]{1,3}", "", s).strip()
        if re.fullmatch(r"\d{6}", cleaned):
            out.append(cleaned)
    return out


def _strip_html_keep_br(s: str) -> str:
    """保留 <br> 为换行，其它 tag 去掉。"""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _parse_tables_with_headers(html: str) -> list[tuple[list[str], list[list[str]]]]:
    """从 HTML 中抽取所有 <table>，返回 [(headers, rows), ...]。

    rows 是 list[list[str]]，每行长度对齐 headers。
    """
    out: list[tuple[list[str], list[list[str]]]] = []
    for table in re.findall(r"<table[^>]*>(.*?)</table>", html, re.DOTALL):
        # headers
        th_match = re.search(r"<thead[^>]*>(.*?)</thead>", table, re.DOTALL)
        head_html = th_match.group(1) if th_match else ""
        if not head_html:
            # 兼容：用第一行 tr 当 header
            first_tr = re.search(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL)
            head_html = first_tr.group(1) if first_tr else ""
        headers = [_strip_html(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", head_html, re.DOTALL)]
        if not headers:
            headers = [_strip_html(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", head_html, re.DOTALL)]
        # body
        tb_match = re.search(r"<tbody[^>]*>(.*?)</tbody>", table, re.DOTALL)
        tbody = tb_match.group(1) if tb_match else table
        rows: list[list[str]] = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.DOTALL):
            tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.DOTALL)
            if not tds:
                continue
            cells = [_strip_html_keep_br(c) for c in tds]
            # 跳过表头行
            if cells == headers:
                continue
            rows.append(cells)
        if headers:
            out.append((headers, rows))
    return out


def _is_candidate_table(headers: list[str]) -> bool:
    s = "|".join(headers)
    return all(k in s for k in CANDIDATE_HEAD_KEYS) and any(g in s for g in GROUP_COL_ALIASES)


def _is_reference_table(headers: list[str]) -> bool:
    """20%/30%参考表头检测。"""
    s = "|".join(headers)
    return "代码" in s and "名称" in s and ("处理" in s or "类型" in s) and "涨跌幅" in s


def parse_html_candidates(pool: StockPool) -> list[dict]:
    """从 `_分析结论.html` 中抽取候选池表格行，按表头动态对位。

    返回标准化 dict（带 normalized key），并附带 raw 列。
    """
    if not pool.html_path or not pool.html_path.exists():
        return []
    text = read_text(pool.html_path)
    tables = _parse_tables_with_headers(text)
    out: list[dict] = []
    for headers, rows in tables:
        if not _is_candidate_table(headers):
            continue
        for cells in rows:
            rec_raw = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(headers)}
            std = _normalize_candidate(rec_raw, headers)
            std["__raw"] = rec_raw
            std["__headers"] = headers
            if std.get("代码") or std.get("名称"):
                out.append(std)
    return out


def parse_html_references(pool: StockPool) -> list[dict]:
    """抽取 20%/30% 参考表（仅供主题/情绪参考，不可执行）。"""
    if not pool.html_path or not pool.html_path.exists():
        return []
    text = read_text(pool.html_path)
    tables = _parse_tables_with_headers(text)
    out: list[dict] = []
    for headers, rows in tables:
        if not _is_reference_table(headers):
            continue
        for cells in rows:
            rec = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(headers)}
            out.append(rec)
    return out


def _pick(rec: dict, *names: str) -> str:
    for n in names:
        if n in rec and rec[n] != "":
            return rec[n]
    return ""


def _normalize_candidate(rec: dict, headers: list[str]) -> dict:
    """把不同版本 HTML 的列名映射到一组稳定字段。"""
    return {
        "分组": _pick(rec, "分组", "层级", "级别"),
        "代码": _pick(rec, "代码"),
        "名称": _pick(rec, "名称"),
        "角色": _pick(rec, "角色"),
        "评分": _pick(rec, "评分", "分"),
        "执行优先级": _pick(rec, "执行优先级"),
        "梯队": _pick(rec, "梯队", "连板"),
        "行业": _pick(rec, "行业"),
        "题材": _pick(rec, "题材"),
        "首次封板": _pick(rec, "首次封板", "首封"),
        "最后封板": _pick(rec, "最后封板", "末封"),
        "炸板": _pick(rec, "炸板"),
        "成交额": _pick(rec, "成交额", "成交额(亿)"),
        "换手": _pick(rec, "换手", "换手率"),
        "封单资金": _pick(rec, "封单资金"),
        "前压/日期": _pick(rec, "前压/日期", "近30日压力"),
        "压力日": _pick(rec, "压力日"),
        "60日区间位置": _pick(rec, "60日区间位置"),
        "距60日低点": _pick(rec, "距60日低点"),
        "次日板价/结构": _pick(rec, "次日板价/结构", "次日涨停价"),
        "结构": _pick(rec, "结构"),
        "临盘触发条件": _pick(rec, "临盘触发条件", "触发"),
        "放弃条件": _pick(rec, "放弃条件", "放弃"),
    }


def list_scripts() -> list[Path]:
    """列出可选股脚本（generate_fengmang_breakout_*.py）。"""
    return CONFIG.legacy_glob("stock_pick_script_glob")


def latest_pool() -> StockPool | None:
    pools = list_pools()
    return pools[0] if pools else None
